
const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
let selectedFile=null;

$$(".nav").forEach(b=>b.onclick=()=>{$$(".nav").forEach(x=>x.classList.remove("active"));b.classList.add("active");$$(".view").forEach(x=>x.classList.remove("active"));$("#"+b.dataset.view).classList.add("active");if(b.dataset.view==="library") loadLibrary()});
$$(".tab").forEach(b=>b.onclick=()=>{$$(".tab").forEach(x=>x.classList.remove("active"));b.classList.add("active");$$(".tabpane").forEach(x=>x.classList.remove("active"));$("#tab-"+b.dataset.tab).classList.add("active")});
$("#fileInput").onchange=e=>{selectedFile=e.target.files[0];$("#fileMeta").textContent=selectedFile?`${selectedFile.name} · ${(selectedFile.size/1024/1024).toFixed(1)} MB`:""};

function esc(s=""){return s.replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}
function showLoading(on){$("#loading").classList.toggle("hidden",!on)}
function renderResult(d){
 const i=d.insight||{};
 const angles=(i.content_angles||[]).map(x=>`<div class="chip">${esc(x)}</div>`).join("");
 const hooks=(i.hooks||[]).map(x=>`<div class="chip">${esc(x)}</div>`).join("");
 $("#result").innerHTML=`<div class="result-card card">
 <div class="kicker">Core insight</div><div class="core">${esc(i.core_insight||"")}</div>
 <div class="cols"><div class="mini"><b>AUDIENCE</b><p>${esc(i.audience||"")}</p></div><div class="mini"><b>TENSION / DESIRE</b><p>${esc(i.tension||"")}</p></div></div>
 <div style="margin-top:20px"><div class="kicker">Content angles</div><div class="angle-list">${angles}</div></div>
 <div style="margin-top:20px"><div class="kicker">Hooks</div><div class="angle-list">${hooks}</div></div>
 </div>`;
}
function showError(msg){$("#result").innerHTML=`<div class="error">${esc(msg)}</div>`}

$("#analyzeText").onclick=async()=>{
 const text=$("#textInput").value.trim(); if(!text)return showError("Hãy nhập nội dung cần phân tích.");
 showLoading(true);$("#result").innerHTML="";
 try{
  const r=await fetch("/api/analyze-text",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text,name:$("#textName").value})});
  const d=await r.json(); if(!r.ok)throw new Error(d.error||"Có lỗi");renderResult(d)
 }catch(e){showError(e.message)}finally{showLoading(false)}
};
$("#analyzeFile").onclick=async()=>{
 if(!selectedFile)return showError("Hãy chọn ảnh hoặc video.");
 showLoading(true);$("#result").innerHTML="";
 try{
  const fd=new FormData();fd.append("file",selectedFile);
  const r=await fetch("/api/analyze-file",{method:"POST",body:fd});const d=await r.json();if(!r.ok)throw new Error(d.error||"Có lỗi");renderResult(d)
 }catch(e){showError(e.message)}finally{showLoading(false)}
};
async function loadLibrary(){
 const q=$("#search").value.trim();const r=await fetch("/api/insights?q="+encodeURIComponent(q));const rows=await r.json();
 $("#libraryGrid").innerHTML=rows.length?rows.map(x=>{
  let tags=[];try{tags=JSON.parse(x.tags||"[]")}catch{}
  return `<article class="lib"><div class="lib-top"><span>${esc(x.source_type.toUpperCase())} · ${esc(x.source_name||"")}</span><span>${esc((x.created_at||"").slice(0,10))}</span></div>
  <h3>${esc(x.core_insight||"")}</h3><div class="tags">${tags.map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>
  <footer><select onchange="setStatus(${x.id},this.value)">${["New","Approved","Used","Archived"].map(s=>`<option ${x.status===s?"selected":""}>${s}</option>`).join("")}</select><button class="delete" onclick="del(${x.id})">Xóa</button></footer></article>`
 }).join(""):`<div class="hint">Chưa có insight nào.</div>`
}
async function setStatus(id,status){await fetch(`/api/insights/${id}/status`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status})})}
async function del(id){if(confirm("Xóa insight này?")){await fetch(`/api/insights/${id}`,{method:"DELETE"});loadLibrary()}}
$("#refresh").onclick=loadLibrary;$("#search").oninput=()=>{clearTimeout(window._t);window._t=setTimeout(loadLibrary,250)}
