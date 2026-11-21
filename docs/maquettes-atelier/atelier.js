// Bascules de présentation : thème, mode, états. Aucune dépendance.
(function(){
  var h=document.documentElement,q=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
  function press(group,val){q('button',group).forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.v===val))})}
  function theme(v){var t=v==='system'?(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'):v;h.dataset.theme=t;press(document.getElementById('b-theme'),v);try{localStorage.setItem('mq-theme',v)}catch(e){}}
  function mode(v){h.dataset.mode=v;press(document.getElementById('b-mode'),v);try{localStorage.setItem('mq-mode',v)}catch(e){}}
  function all(on){if(on)h.setAttribute('data-all','');else h.removeAttribute('data-all');var b=document.getElementById('b-all');if(b)b.setAttribute('aria-pressed',String(on))}
  var g=function(k,d){try{return localStorage.getItem(k)||d}catch(e){return d}};
  q('#b-theme button').forEach(function(b){b.onclick=function(){theme(b.dataset.v)}});
  q('#b-mode button').forEach(function(b){b.onclick=function(){mode(b.dataset.v)}});
  var ba=document.getElementById('b-all');if(ba)ba.onclick=function(){all(!h.hasAttribute('data-all'))};
  theme(g('mq-theme','system'));mode(g('mq-mode','simple'));
  q('.fiche').forEach(function(f){
    var tabs=q('.tabs button',f),frames=q('.frame',f);
    function pick(k){tabs.forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.s===k))});frames.forEach(function(fr){fr.classList.toggle('on',fr.dataset.st===k)})}
    tabs.forEach(function(b){b.onclick=function(){pick(b.dataset.s)}});
    if(tabs[0])pick(tabs[0].dataset.s);
  });
})();
