const $=id=>document.getElementById(id);
const downloadBtn=$("downloadBtn"),uploadBtn=$("uploadBtn"),downloadStatus=$("downloadStatus"),uploadStatus=$("uploadStatus"),bar=$("bar"),summary=$("summary"),details=$("details");

async function pollJob(jobId,statusEl){
  for(;;){
    const r=await fetch("/jobs/"+encodeURIComponent(jobId));
    const d=await r.json();
    statusEl.textContent=d.message||d.status;
    if(d.status==="completed"||d.status==="failed"){
      return d;
    }
    await new Promise(resolve=>setTimeout(resolve,1500));
  }
}

downloadBtn.onclick=async()=>{
  downloadBtn.disabled=true;
  downloadStatus.textContent="Starting Blinkit report job...";
  try{
    const r=await fetch("/blinkit/download",{method:"POST"});
    const d=await r.json();
    if(!r.ok) throw new Error(d.detail||"Download failed");
    const job=await pollJob(d.job_id,downloadStatus);
    if(job.status==="failed") throw new Error(job.error||"Download failed");
    downloadStatus.textContent="Blinkit report download completed.";
    details.textContent=JSON.stringify(job.results||[],null,2);
  }catch(e){
    downloadStatus.textContent="Error: "+e.message;
  }finally{downloadBtn.disabled=false}
};

uploadBtn.onclick=async()=>{
  uploadBtn.disabled=true;
  bar.style.width="10%";
  uploadStatus.textContent="Starting Google Sheets sync...";
  summary.textContent="Processing all downloaded reports...";
  details.textContent="";
  try{
    const r=await fetch("/sheets/upload",{method:"POST"});
    const d=await r.json();
    if(!r.ok) throw new Error(d.detail||"Upload failed");
    const job=await pollJob(d.job_id,uploadStatus);
    if(job.status==="failed") throw new Error(job.error||"Google Sheets sync failed");

    const results=job.results||[];
    const added=results.reduce((n,x)=>n+(x.added||0),0);
    const skipped=results.reduce((n,x)=>n+(x.skipped_duplicates||0),0);
    const exceptions=results.filter(x=>["ERROR","SCHEMA_MISMATCH","AMBIGUOUS_TAB"].includes(x.status)).length;
    const driveUploaded=results.filter(x=>x.drive&&x.drive.status==="UPLOADED").length;

    bar.style.width="100%";
    summary.textContent=results.length+" products processed • "+added.toLocaleString()+" rows added • "+skipped.toLocaleString()+" duplicates skipped • "+driveUploaded+" Drive files archived • "+exceptions+" exceptions";
    uploadStatus.textContent="Google Sheets sync completed.";
    details.textContent=JSON.stringify(results,null,2);
  }catch(e){
    uploadStatus.textContent="Error: "+e.message;
    bar.style.width="0%";
  }finally{uploadBtn.disabled=false}
};