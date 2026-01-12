document.addEventListener('DOMContentLoaded',function(){
const sidebar=document.getElementById('sidebar');
const overlay=document.getElementById('overlay');
const menuToggle=document.getElementById('menuToggle');
const sidebarClose=document.getElementById('sidebarClose');
if(menuToggle){menuToggle.addEventListener('click',()=>{sidebar.classList.add('open');overlay.classList.add('show')});}
if(sidebarClose){sidebarClose.addEventListener('click',()=>{sidebar.classList.remove('open');overlay.classList.remove('show')});}
if(overlay){overlay.addEventListener('click',()=>{sidebar.classList.remove('open');overlay.classList.remove('show')});}
document.querySelectorAll('.toggle-pass').forEach(btn=>{
btn.addEventListener('click',function(){
const input=this.parentElement.querySelector('input');
if(input.type==='password'){input.type='text';this.textContent='🙈';}
else{input.type='password';this.textContent='👁';}
});
});
document.querySelectorAll('form[data-confirm]').forEach(form=>{
form.addEventListener('submit',function(e){
if(!confirm(form.getAttribute('data-confirm'))){e.preventDefault();}
});
});
document.querySelectorAll('form[action*="start-bot"],form[action*="stop-bot"]').forEach(form=>{
form.addEventListener('submit',function(){
const btn=form.querySelector('button[type="submit"]');
if(btn){btn.disabled=true;btn.textContent='...';}
setTimeout(()=>window.location.reload(),1000);
});
});
const usersCanvas=document.getElementById('newUsersChart');
if(usersCanvas&&typeof CHART_DATA!=='undefined'){
const chartOpts={
responsive:true,
maintainAspectRatio:false,
plugins:{legend:{display:false}},
scales:{
x:{grid:{color:'#2a2a2a'},ticks:{color:'#888',maxTicksLimit:10,maxRotation:0}},
y:{grid:{color:'#2a2a2a'},ticks:{color:'#888',precision:0},beginAtZero:true}
}
};
function prepareData(data,color){
const labels=[],values=[];
const today=new Date();
for(let i=29;i>=0;i--){
const d=new Date(today);d.setDate(today.getDate()-i);
const ds=d.toISOString().split('T')[0];
labels.push(`${d.getDate()}.${d.getMonth()+1}`);
values.push(data[ds]||0);
}
return{labels,datasets:[{data:values,borderColor:color,backgroundColor:color+'33',borderWidth:2,fill:true,tension:.3,pointRadius:0}]};
}
new Chart(usersCanvas.getContext('2d'),{type:'line',data:prepareData(CHART_DATA.users,'#6366f1'),options:chartOpts});
const keysCanvas=document.getElementById('newKeysChart');
if(keysCanvas){new Chart(keysCanvas.getContext('2d'),{type:'line',data:prepareData(CHART_DATA.keys,'#22c55e'),options:chartOpts});}
}
document.querySelectorAll('.clickable-row').forEach(row=>{
row.addEventListener('click',function(e){
if(e.target.tagName!=='A'&&e.target.tagName!=='BUTTON'){window.location=this.dataset.href;}
});
});
});
