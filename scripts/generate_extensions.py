"""Generate self-contained unpacked browser connectors from shared audited code."""
import json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def generate():
    shared=ROOT/'browser-extension/shared'
    base={'manifest_version':3,'name':'ChessLens — Chess.com Connector','version':'1.3.0',
          'description':'Local Stockfish analysis, board markers and optional visual title badges. Never plays moves.',
          'host_permissions':['https://www.chess.com/*','https://chess.com/*','http://127.0.0.1:37391/*'],
          'content_scripts':[
              {'matches':['https://www.chess.com/*','https://chess.com/*'],'js':['page-state.js'],'world':'MAIN','run_at':'document_idle'},
              {'matches':['https://www.chess.com/*','https://chess.com/*'],'js':['titles.js','connector.js'],'run_at':'document_idle'}]}
    for browser in ['chromium','firefox']:
        target=ROOT/'browser-extension'/browser;target.mkdir(exist_ok=True)
        manifest=dict(base)
        if browser=='firefox':
            manifest.update(background={'scripts':['background.js']},browser_specific_settings={'gecko':{'id':'chesslens@local.invalid','strict_min_version':'140.0'}})
        else:manifest['background']={'service_worker':'background.js'}
        (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        for source in shared.glob('*.js'):shutil.copy2(source,target/source.name)
        if (ROOT/'docs/SETUP.html').exists():shutil.copy2(ROOT/'docs/SETUP.html',target/'SETUP.html')

if __name__=='__main__':generate()
