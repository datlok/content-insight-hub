
const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
let selectedFile=null,designRefFile=null,designPhotoFile=null;
function switchView(id){$$(".nav").forEach(x=>x.classList.toggle("active",x.dataset.view===id));$$(".view").forEach(x=>x.classList.toggle("active",x.id===id));if(id==="library")loadLibrary()}
$$(".nav").forEach(b=>b.onclick=()=>switchView(b.dataset.view));
$$(".tab").forEach(b=>b.onclick=()=>{$$(".tab").forEach(x=>x.classList.remove("active"));b.classList.add("active");$$(".tabpane").forEach(x=>x.classList.remove("active"));$("#tab-"+b.dataset.tab).classList.add("active")});
$("#fileInput").onchange=e=>{selectedFile=e.target.files[0];$("#fileMeta").textContent=selectedFile?`${selectedFile.name} · ${(selectedFile.size/1024/1024).toFixed(1)} MB`:""};
function esc(s=""){return String(s).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}
function loading(sel,on){$(sel).classList.toggle("hidden",!on)} function showErr(sel,msg){$(sel).innerHTML=`<div class="error">${esc(msg)}</div>`}
function buildWriterContext(i){
  let angles=i.content_angles||[];
  if(typeof angles==="string"){try{angles=JSON.parse(angles)}catch{angles=[]}}
  return [
    `CORE INSIGHT:
${i.core_insight||""}`,
    i.summary?`SUMMARY:
${i.summary}`:"",
    i.audience?`AUDIENCE:
${i.audience}`:"",
    i.tension?`TENSION / DESIRE:
${i.tension}`:"",
    angles.length?`CONTENT ANGLES:
- ${angles.join("
- ")}`:""
  ].filter(Boolean).join("

")
}
function renderInsight(d){
  const i=d.insight||{},angles=(i.content_angles||[]).map(x=>`<div class="chip">${esc(x)}</div>`).join(""),hooks=(i.hooks||[]).map(x=>`<div class="chip">${esc(x)}</div>`).join("");
  const ctx=encodeURIComponent(buildWriterContext(i));
  $("#result").innerHTML=`<div class="result-card card"><div class="kicker">Core insight</div><div class="core">${esc(i.core_insight||"")}</div><button class="write-btn" onclick="openWriterAndGenerate(decodeURIComponent('${ctx}'))">✎ Viết ngay 2 phiên bản</button><div class="cols" style="margin-top:14px"><div class="mini"><b>AUDIENCE</b><p>${esc(i.audience||"")}</p></div><div class="mini"><b>TENSION / DESIRE</b><p>${esc(i.tension||"")}</p></div></div><div style="margin-top:20px"><div class="kicker">Content angles</div><div class="angle-list">${angles}</div></div><div style="margin-top:20px"><div class="kicker">Hooks</div><div class="angle-list">${hooks}</div></div></div>`
}
$("#analyzeText").onclick=async()=>{const text=$("#textInput").value.trim();if(!text)return showErr("#result","Hãy nhập nội dung.");loading("#loading",true);$("#result").innerHTML="";try{const r=await fetch("/api/analyze-text",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text,name:$("#textName").value})}),d=await r.json();if(!r.ok)throw Error(d.error||"Có lỗi");renderInsight(d)}catch(e){showErr("#result",e.message)}finally{loading("#loading",false)}}
$("#analyzeFile").onclick=async()=>{if(!selectedFile)return showErr("#result","Hãy chọn ảnh hoặc video.");loading("#loading",true);$("#result").innerHTML="";try{const fd=new FormData();fd.append("file",selectedFile);const r=await fetch("/api/analyze-file",{method:"POST",body:fd}),d=await r.json();if(!r.ok)throw Error(d.error||"Có lỗi");renderInsight(d)}catch(e){showErr("#result",e.message)}finally{loading("#loading",false)}}
async function loadLibrary(){
  const r=await fetch("/api/insights?q="+encodeURIComponent($("#search").value.trim())),rows=await r.json();
  $("#libraryGrid").innerHTML=rows.length?rows.map(x=>{
    let tags=[];try{tags=JSON.parse(x.tags||"[]")}catch{}
    const ctx=encodeURIComponent(buildWriterContext(x));
    return `<article class="lib"><div class="lib-top"><span>${esc(x.source_type.toUpperCase())} · ${esc(x.source_name||"")}</span><span>${esc((x.created_at||"").slice(0,10))}</span></div><h3>${esc(x.core_insight||"")}</h3><div class="tags">${tags.map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div><button class="write-btn" onclick="openWriterAndGenerate(decodeURIComponent('${ctx}'))">✎ Viết ngay 2 phiên bản</button><footer><select onchange="setStatus(${x.id},this.value)">${["New","Approved","Used","Archived"].map(s=>`<option ${x.status===s?"selected":""}>${s}</option>`).join("")}</select><button class="delete" onclick="delInsight(${x.id})">Xóa</button></footer></article>`
  }).join(""):`<div class="hint">Chưa có insight nào.</div>`
}
window.openWriter=t=>{$("#writerInsight").value=t;switchView("writer");window.scrollTo(0,0)}
window.openWriterAndGenerate=async t=>{
  $("#writerInsight").value=t;
  switchView("writer");
  window.scrollTo(0,0);
  await generateContentNow();
}
window.setStatus=async(id,status)=>{await fetch(`/api/insights/${id}/status`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status})})}
window.delInsight=async id=>{if(confirm("Xóa insight này?")){await fetch(`/api/insights/${id}`,{method:"DELETE"});loadLibrary()}}
$("#refresh").onclick=loadLibrary;$("#search").oninput=()=>{clearTimeout(window._t);window._t=setTimeout(loadLibrary,250)}
async function generateContentNow(){
  const insight=$("#writerInsight").value.trim();
  if(!insight)return showErr("#writerResult","Hãy nhập insight.");
  loading("#writerLoading",true);
  $("#writerResult").innerHTML="";
  try{
    const r=await fetch("/api/write-content",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
      insight,
      platform:$("#writerPlatform").value,
      objective:$("#writerObjective").value,
      extra_request:$("#writerExtra").value
    })});
    const d=await r.json();
    if(!r.ok)throw Error(d.error||"Có lỗi");
    $("#writerResult").innerHTML=[d.short_hook||{},d.sales_cta||{}].map((x,i)=>`<div class="content-version card"><div class="kicker">Version ${i+1}</div><h3>${esc(x.title||"")}</h3><div class="content-body">${esc(x.content||"")}</div><button class="copy-btn" data-copy="${encodeURIComponent(x.content||"")}">Copy</button></div>`).join("");
    $$(".copy-btn").forEach(b=>b.onclick=()=>navigator.clipboard.writeText(decodeURIComponent(b.dataset.copy)));
  }catch(e){showErr("#writerResult",e.message)}
  finally{loading("#writerLoading",false)}
}
$("#generateContent").onclick=generateContentNow;
function preview(input,imgSel){const f=input.files[0];if(!f)return null;const img=$(imgSel);img.src=URL.createObjectURL(f);img.parentElement.classList.add("has-image");return f}
$("#designRef").onchange=e=>designRefFile=preview(e.target,"#refPreview");$("#designPhoto").onchange=e=>designPhotoFile=preview(e.target,"#photoPreview");
$("#generateDesign").onclick=async()=>{const instruction=$("#designInstruction").value.trim();if(!designRefFile)return showErr("#designResult","Hãy upload ảnh reference design.");if(!designPhotoFile)return showErr("#designResult","Hãy upload ảnh chụp bên mình.");if(!instruction)return showErr("#designResult","Hãy nhập yêu cầu thiết kế.");loading("#designLoading",true);$("#designResult").innerHTML="";try{const fd=new FormData();fd.append("reference",designRefFile);fd.append("photo",designPhotoFile);fd.append("instruction",instruction);fd.append("size",$("#designSize").value);const r=await fetch("/api/generate-design",{method:"POST",body:fd}),d=await r.json();if(!r.ok)throw Error(d.error||"Có lỗi");const src=`data:${d.mime||"image/png"};base64,${d.image_base64}`;$("#designResult").innerHTML=`<div class="generated-design card"><img src="${src}" alt="Generated design"><br><a class="download-btn" href="${src}" download="design.png">↓ Lưu ảnh</a></div>`}catch(e){showErr("#designResult",e.message)}finally{loading("#designLoading",false)}}
