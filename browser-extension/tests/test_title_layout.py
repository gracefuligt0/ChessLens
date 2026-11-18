"""Real browser geometry checks for inline player title badges."""
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPT=Path(__file__).resolve().parents[1]/'shared/titles.js'

class TitleLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright=sync_playwright().start();cls.browser=cls.playwright.chromium.launch(headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.playwright.stop()
    def setUp(self):self.page=self.browser.new_page(viewport={'width':1200,'height':1100})
    def tearDown(self):self.page.close()
    def fixture(self,style='span',zoom=1):
        def header(position,name):
            if style=='button':label=f'<button class="user-tagline-username"><span>{name}</span></button>'
            else:label=f'<span class="username">{name}</span>'
            return f'<div class="player-component {position}"><div class="username-container"><div class="avatar"></div><div class="information"><div class="name-row"><span class="user-tagline-title">CM</span>{label}<span class="rating">(2538)</span><span class="flag">⚑</span></div><div class="material">♟ ♞ +2</div></div></div></div>'
        html='''<style>body{margin:20px;font:14px/20px Arial;background:#282827;color:white}.player-component{height:48px;width:700px}.username-container{display:flex;gap:10px;align-items:flex-start}.avatar{width:40px;height:40px;background:#888;flex:none}.information{display:flex;flex-direction:column}.name-row{display:flex;align-items:center;gap:4px}.username,button{font:700 14px/20px Arial;color:white}button{display:block;border:0;background:none;margin:0;padding:0;cursor:pointer}.user-tagline-title{background:#b33430;border-radius:2px;padding:1px 3px;font:bold 11px/12px Arial}.material{height:20px}.board{width:700px;height:700px;background:#769656}</style>'''+header('top','MagnusCarlsen')+'<div class="board"></div>'+header('bottom','Witty_Alien')
        self.page.set_content(html);self.page.evaluate('(zoom)=>document.body.style.zoom=zoom',zoom)
        self.page.add_script_tag(path=str(SCRIPT))
        self.before=self.page.evaluate('''() => Object.fromEntries(['top','bottom'].map(side=>{const root=document.querySelector('.'+side);const a=root.querySelector('.avatar').getBoundingClientRect();const r=root.getBoundingClientRect();return [side,{avatarX:a.x,avatarY:a.y,headerHeight:r.height}]}))''')
    def update(self,own='GM',opponent='IM',white_bottom=True):
        self.page.evaluate('''({own,opponent,whiteBottom})=>{
            const r=document.querySelector('.board').getBoundingClientRect();
            ChessLensTitles.update({visible:true,whiteBottom,player:'white',rect:{x:r.x,y:r.y,width:r.width,height:r.height}}, {selfTitle:own,opponentTitle:opponent}, 'white');
        }''',{'own':own,'opponent':opponent,'whiteBottom':white_bottom})
    def geometry(self,side):
        return self.page.evaluate('''side=>{
          const row=document.querySelector('.'+side);const badge=row.querySelector('[data-chesslens-title]');if(!badge)return null;
          const name=row.querySelector('.username,.user-tagline-username');const walker=document.createTreeWalker(name,NodeFilter.SHOW_TEXT);let text;
          while(walker.nextNode()){if(!walker.currentNode.parentElement.closest('[data-chesslens-title]')&&walker.currentNode.textContent.trim()){text=walker.currentNode;break;}}
          const range=document.createRange();range.selectNodeContents(text);const n=range.getBoundingClientRect(),b=badge.getBoundingClientRect(),a=row.querySelector('.avatar').getBoundingClientRect(),r=row.getBoundingClientRect();
          return {badgeLeft:b.left,badgeRight:b.right,badgeCenter:(b.top+b.bottom)/2,nameLeft:n.left,nameCenter:(n.top+n.bottom)/2,avatarRight:a.right,avatarX:a.x,avatarY:a.y,headerHeight:r.height,title:badge.textContent};
        }''',side)
    def assert_inline(self,side,zoom=1):
        g=self.geometry(side);self.assertIsNotNone(g,'Badge should be in the player name line')
        self.assertGreaterEqual(g['badgeLeft'],g['avatarRight'])
        self.assertLessEqual(abs(g['badgeCenter']-g['nameCenter']),2.5*zoom)
        self.assertGreaterEqual(g['nameLeft']-g['badgeRight'],2*zoom)
        self.assertLessEqual(g['nameLeft']-g['badgeRight'],6*zoom)
        self.assertAlmostEqual(g['avatarX'],self.before[side]['avatarX']);self.assertAlmostEqual(g['avatarY'],self.before[side]['avatarY'])
        self.assertAlmostEqual(g['headerHeight'],self.before[side]['headerHeight'])
    def test_wrapping_container_does_not_put_the_badge_before_the_avatar(self):
        self.fixture();self.update();self.assert_inline('top');self.assert_inline('bottom')
    def test_block_username_button_keeps_badge_on_the_name_baseline(self):
        self.fixture('button');self.update();self.assert_inline('top');self.assert_inline('bottom')
    def test_zoom_and_longer_title_keep_the_same_alignment(self):
        self.fixture('button',1.25);self.update('WGM','WIM');self.assert_inline('top',1.25);self.assert_inline('bottom',1.25)
    def test_independent_toggles_restore_native_titles(self):
        self.fixture();self.update();self.update(None,'FM')
        self.assertEqual(self.page.locator('.bottom [data-chesslens-title]').count(),0)
        self.assertNotEqual(self.page.locator('.bottom .user-tagline-title').evaluate('(n)=>getComputedStyle(n).display'),'none')
        self.assertEqual(self.page.locator('.top [data-chesslens-title]').inner_text(),'FM')
        self.update(None,None);self.assertEqual(self.page.locator('[data-chesslens-title]').count(),0)
    def test_repeated_updates_and_player_header_renders_never_duplicate_badges(self):
        self.fixture('button')
        for _ in range(6):self.update()
        self.assertEqual(self.page.locator('[data-chesslens-title]').count(),2)
        self.page.evaluate("document.querySelector('.bottom .information').innerHTML='<div class=\"name-row\"><button class=\"user-tagline-username\"><span>AnotherPlayer</span></button><span>(2538)</span></div><div class=\"material\">♟</div>'")
        self.update();self.assertEqual(self.page.locator('[data-chesslens-title]').count(),2);self.assert_inline('bottom')
    def test_board_flip_keeps_each_title_with_the_correct_player_side(self):
        self.fixture();self.update('GM','WGM',False)
        self.assertEqual(self.page.locator('.top [data-chesslens-title="self"]').inner_text(),'GM')
        self.assertEqual(self.page.locator('.bottom [data-chesslens-title="opponent"]').inner_text(),'WGM')

if __name__=='__main__':unittest.main(verbosity=2)
