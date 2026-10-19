"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "./client";

type Run = {id:string;status:string;provider:string;model:string;attempt:number;error:string|null;retryable:boolean;result:{revision?:number;questions?:string[]}|null;extraction:{lines:{query:string;quantity:string|null;unit:string|null;source:string}[];requirements:string[];conditions:string[]}|null;calls:{kind:string;name:string;arguments:unknown;output:unknown;error:string|null;duration_ms:number;usage:{total_tokens?:number}|null}[]};
const names:Record<string,string> = {queued:"В очереди",running:"Обработка",completed:"Черновик готов",needs_clarification:"Нужно уточнение",manual_review:"Ручная проверка",failed:"Ошибка обработки"};

export default function ProcessingPanel({inquiry,onUpdated,onBusy}:{inquiry:{id:string;revision:number;confirmed_revision:number|null};onUpdated:()=>Promise<void>;onBusy:(value:boolean)=>void}) {
  const [runs,setRuns]=useState<Run[]>([]),[clarification,setClarification]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const operation=useRef({payload:"",key:""}),notified=useRef(inquiry.revision);
  const latest=runs[0];
  useEffect(()=>{notified.current=Math.max(notified.current,inquiry.revision);},[inquiry.revision]);
  useEffect(()=>{
    let cancelled=false;
    async function poll(){
      try {
        const result=await api<Run[]>(`/inquiries/${inquiry.id}/runs`);
        if(cancelled)return;
        setRuns(result);
        onBusy(result.some(r=>r.status==="queued" || (r.status==="running" && !r.retryable)));
        const completed=result.find(r=>r.status==="completed" && (r.result?.revision||0)>notified.current);
        if(completed){notified.current=completed.result!.revision!;await onUpdated();}
      } catch(e){if(!cancelled)setError(e instanceof Error?e.message:"Не удалось получить статус");}
    }
    void poll();const timer=setInterval(()=>void poll(),1800);
    return()=>{cancelled=true;clearInterval(timer);onBusy(false);};
  // A panel instance belongs to one inquiry; polling uses its initial refresh callback.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[inquiry.id]);
  async function action(retry=false){
    setBusy(true);setError("");
    try{
      if(retry && latest) await api(`/inquiries/${inquiry.id}/runs/${latest.id}/retry`,{});
      else{
        const payload=JSON.stringify({clarification,revision:inquiry.revision});
        if(operation.current.payload!==payload || !operation.current.key)operation.current={payload,key:crypto.randomUUID()};
        await api(`/inquiries/${inquiry.id}/process`,{clarification},operation.current.key);
      }
      const result=await api<Run[]>(`/inquiries/${inquiry.id}/runs`);setRuns(result);
      onBusy(result.some(r=>["queued","running"].includes(r.status)));
    }catch(e){setError(e instanceof Error?e.message:"Ошибка обработки");}finally{setBusy(false);}
  }
  const running=latest && ["queued","running"].includes(latest.status);
  return <section className="panel"><div className="section-title"><span>AI</span><h2>Разбор и предварительное КП</h2></div>
    <p className="note">Агент ищет точное исполнение и получает коммерческие данные из каталога. Цены, скидки, сроки и итог требуют вашей проверки.</p>
    {latest && <p className="processing-status" role="status">{names[latest.status]||latest.status} · {latest.provider==="mock"?"MOCK — без внешнего LLM":"LLM"} · попытка {latest.attempt}</p>}
    {!inquiry.confirmed_revision && <><label>Уточнённый перечень (полностью заменяет разбор исходной заявки)<textarea rows={2} maxLength={20000} value={clarification} disabled={busy||!!running} onChange={e=>setClarification(e.target.value)} placeholder="Например: SKU-0001, 2 шт. Каждая позиция с новой строки."/></label>
      <div className="downloads"><button disabled={busy||!!running} onClick={()=>void action()}>Разобрать заявку и создать черновик</button>{latest?.retryable && <button className="quiet" disabled={busy} onClick={()=>void action(true)}>Повторить задачу / постановку в очередь</button>}</div></>}
    {latest?.result?.questions && latest.result.questions.length>0 && <ul className="review-questions">{latest.result.questions.map((q,i)=><li key={i}>{q}</li>)}</ul>}
    {latest?.error && <p className="error">Обработка остановлена: {latest.error}. Исправьте причину или передайте заявку на ручную проверку.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {latest?.extraction && <details><summary>Извлечённые позиции, требования и условия</summary>{latest.extraction.lines.map((l,i)=><p key={i}>{i+1}. {l.query} · {l.quantity||"количество не указано"} {l.unit||""}<small>Источник: {l.source}</small></p>)}{[...latest.extraction.requirements,...latest.extraction.conditions].map((s,i)=><p key={i}>{s}</p>)}<p className="note">Условия клиента сохраняются как запрос, коммерческие обещания из них автоматически не создаются.</p></details>}
    {latest?.calls.length ? <details><summary>Инструменты и журнал агента ({latest.calls.length})</summary>{latest.calls.map((c,i)=><div className="agent-call" key={i}><b>{c.kind} / {c.name}</b> · {c.duration_ms} мс {c.usage?.total_tokens!==undefined?`· ${c.usage.total_tokens} токенов`:""}{c.error && <span className="error"> · {c.error}</span>}{c.kind==="tool" && <pre>{JSON.stringify({arguments:c.arguments,result:c.output},null,2)}</pre>}</div>)}</details>:null}
    {runs.length>1 && <details><summary>История обработок ({runs.length})</summary>{runs.map(r=><p key={r.id}>{r.id.slice(0,8)} · {names[r.status]||r.status} · {r.provider} · {r.error||r.result?.questions?.join(" ")}</p>)}</details>}
  </section>;
}
