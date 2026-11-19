const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'static/js/alerts.js'),'utf8');
function setup(sprite) {
  class Element {
    constructor(tag) {this.tag=tag;this.dataset={};this.children=[];this.classList={add(){}};}
    setAttribute(name,value) {this[name]=value;}
    addEventListener() {}
    append(...children) {this.children.push(...children);children.forEach(child=>child.parentElement=this);}
    querySelector(selector) {
      if (selector==='[data-alert-close]') return this.children.find(child=>child.dataset.alertClose==='');
      return null;
    }
    contains() {return false;}
  }
  const document={documentElement:{dataset:sprite?{iconSprite:sprite}:{}},
    currentScript:{src:'http://localhost:8000/assets/js/alerts.js?v=2'},
    createElement:tag=>new Element(tag),body:new Element('body'),hidden:false,
    querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){},removeEventListener(){}};
  const window={matchMedia:()=>({matches:true})};
  vm.runInNewContext(source,{document,window,URL,performance:{now:()=>0},setTimeout:()=>1,clearTimeout(){}});
  return {window,document};
}
for (const [level,icon] of [['success','circle-check'],['error','circle-xmark'],['warning','triangle-exclamation'],['info','circle-info']]) {
  test(`${level} alert and close icons work without a sprite attribute on cached HTML`,()=>{
    const {window,document}=setup();
    window.appAlerts.show('رسالة تجريبية',level);
    const alert=document.body.children[0].children[0];
    assert.ok(alert.children[0].innerHTML.includes(`/assets/vendor/lucide/masar-icons.svg#${icon}`));
    assert.ok(alert.children[2].innerHTML.includes('/assets/vendor/lucide/masar-icons.svg#xmark'));
    assert.ok(!alert.children[0].innerHTML.includes('undefined'));
  });
}
test('explicit static-storage sprite URL is respected',()=>{
  const {window,document}=setup('/custom/masar-icons.hash.svg');
  window.appAlerts.show('تم الحفظ');
  assert.ok(document.body.children[0].children[0].children[0].innerHTML.includes('/custom/masar-icons.hash.svg#circle-check'));
});
