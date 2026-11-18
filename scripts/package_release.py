"""Create portable binaries, source, browser connectors and SHA-256 checksums."""
import hashlib,zipfile,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION='1.3.1'

def zip_folder(source,path,prefix,include=lambda path:True):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for file in sorted(source.rglob('*')):
            if file.is_file() and include(file):archive.write(file,str(Path(prefix)/file.relative_to(source)))

def source_file(path):
    relative=path.relative_to(ROOT)
    excluded={'.git','.venv','.venv-build','build','dist','release-artifacts','__pycache__'}
    return not any(p in excluded for p in relative.parts) and path.suffix.lower() not in ['.exe','.dll','.pyd','.pyc','.spec','.log','.nnue']

def package():
    target=ROOT/'release-artifacts';target.mkdir(exist_ok=True)
    app=ROOT/'dist/ChessLens'
    if not (app/'ChessLens.exe').is_file():raise RuntimeError('Build the Windows application first.')
    zip_folder(app,target/f'ChessLens-v{VERSION}-Windows-x64.zip','ChessLens')
    zip_folder(ROOT,target/f'ChessLens-v{VERSION}-Source.zip',f'ChessLens-{VERSION}',source_file)
    for browser,folder in [('Chromium','chromium'),('Firefox','firefox')]:
        zip_folder(ROOT/'browser-extension'/folder,target/f'ChessLens-v{VERSION}-{browser}-Connector.zip',f'ChessLens-{browser}-Connector')
    files=sorted(target.glob(f'ChessLens-v{VERSION}-*.zip'))
    (target/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files),encoding='utf-8')
    for path in files:print(f'{path.name}: {path.stat().st_size:,} bytes')
    return files

if __name__=='__main__':package()
