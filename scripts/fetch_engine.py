"""Fetch the official, checksum-pinned Stockfish 19 Windows universal build."""
import hashlib,io,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
URL='https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-windows-x86-64-universal.zip'
ARCHIVE_SHA256='3c8bf1f9ea66a09350a40df4f632288285ac206d99f33ab5842c408fc30b48a7'
EXE_SHA256='45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0'
DEST=ROOT/'src/assets/engine/stockfish/stockfish-windows-x86-64-universal.exe'

def fetch():
    if DEST.is_file() and hashlib.sha256(DEST.read_bytes()).hexdigest()==EXE_SHA256:return DEST
    request=urllib.request.Request(URL,headers={'User-Agent':'ChessLens-build'})
    with urllib.request.urlopen(request,timeout=120) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=ARCHIVE_SHA256:raise RuntimeError('Stockfish archive checksum does not match the official release.')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=[name for name in archive.namelist() if name.endswith('/stockfish-windows-x86-64-universal.exe') or name=='stockfish-windows-x86-64-universal.exe']
        if len(names)!=1:raise RuntimeError('Unexpected Stockfish archive contents.')
        binary=archive.read(names[0])
    if hashlib.sha256(binary).hexdigest()!=EXE_SHA256:raise RuntimeError('Stockfish executable checksum mismatch.')
    DEST.parent.mkdir(parents=True,exist_ok=True);DEST.write_bytes(binary);return DEST

if __name__=='__main__':print(fetch())
