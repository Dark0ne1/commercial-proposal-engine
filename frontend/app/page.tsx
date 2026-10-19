"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, readResponse } from "./client";
import ProcessingPanel from "./ProcessingPanel";
import { formatMoney as amount } from "./money";

type Customer = { id: number; name: string; discount: string; payment_terms: string };
type Product = { id: number; sku: string; name: string; unit: string; price: string; stock: string; lead_days: number };
type Line = { product_id: number; quantity: string; unit: string; unit_price: string };
type Snapshot = { number: string; subtotal: string; discount_amount: string; vat: string; vat_rate: string; total: string; discount: string; payment_terms: string; comments: string; lines: (Line & {name: string; sku: string; amount: string; availability: string})[] };
type Inquiry = { id: string; customer_id: number; text: string; source_info?:{filename?:string}; extracted_text?:string; revision: number; confirmed_revision: number | null; versions?: {revision: number; snapshot: Snapshot}[]; events?: {action: string; actor: string; at: string}[] };
const actionNames: Record<string,string> = {"inquiry.created": "Заявка зарегистрирована", "quote.drafted": "Сохранена версия КП", "quote.confirmed": "Менеджер подтвердил КП", "documents.generated": "Документы созданы", "documents.failed": "Ошибка генерации — можно повторить", "processing.queued":"Обработка поставлена в очередь", "processing.started":"Начат разбор заявки", "document.extracted":"Извлечён текст документа", "processing.completed":"Агент подготовил черновик", "processing.manual_review":"Передано на ручную проверку", "processing.needs_clarification":"Запрошено уточнение", "processing.failed":"Обработка завершилась ошибкой"};

export default function Page() {
  const [logged, setLogged] = useState(false), [loading, setLoading] = useState(true);
  const [mode,setMode]=useState("mock"),[file,setFile]=useState<File|null>(null),[processingBusy,setProcessingBusy]=useState(false);
  const [email, setEmail] = useState("manager@example.test"), [password, setPassword] = useState("");
  const [customers, setCustomers] = useState<Customer[]>([]), [products, setProducts] = useState<Product[]>([]), [inquiries, setInquiries] = useState<Inquiry[]>([]);
  const [customerId, setCustomerId] = useState(1), [text, setText] = useState("");
  const [active, setActive] = useState<Inquiry | null>(null), [lines, setLines] = useState<Line[]>([]);
  const [discount, setDiscount] = useState("0"), [terms, setTerms] = useState("100% предоплата"), [comments, setComments] = useState("");
  const [query, setQuery] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [ready, setReady] = useState(false);
  const operation = useRef<{payload: string; key: string} | null>(null);
  const initialized = useRef(false);
  const snapshot = active?.versions?.at(-1)?.snapshot;
  const confirmed = !!active?.confirmed_revision;
  const loadLists = useCallback(async () => {
    const [c, p, i] = await Promise.all([api<Customer[]>("/customers"), api<Product[]>("/catalog"), api<Inquiry[]>("/inquiries")]);
    setCustomers(c); setProducts(p); setInquiries(i);
    if (!initialized.current && c.length) {
      setCustomerId(c[0].id); setDiscount(c[0].discount); setTerms(c[0].payment_terms);
      initialized.current = true;
    }
  }, []);
  useEffect(() => { api<{mode:string}>("/me").then(async value => { setMode(value.mode); await loadLists(); setLogged(true); }).catch(() => {}).finally(() => setLoading(false)); }, [loadLists]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Ошибка операции"); }
    finally { setBusy(false); }
  }
  function keyFor(payload: unknown) {
    const serialized = JSON.stringify(payload);
    if (operation.current?.payload !== serialized) operation.current = {payload: serialized, key: crypto.randomUUID()};
    return operation.current!.key;
  }
  function selectCustomer(id: number) {
    setCustomerId(id); const c = customers.find(c => c.id === id);
    setDiscount(c?.discount || "0"); setTerms(c?.payment_terms || "100% предоплата");
  }
  async function open(id: string) {
    const value = await api<Inquiry>(`/inquiries/${id}`); setActive(value);
    setCustomerId(value.customer_id); setText(value.text);
    const s = value.versions?.at(-1)?.snapshot;
    setLines(s?.lines.map(l => ({product_id: l.product_id, quantity: l.quantity, unit: l.unit, unit_price: l.unit_price})) || []);
    setDiscount(s?.discount || customers.find(c => c.id === value.customer_id)?.discount || "0");
    setTerms(s?.payment_terms || customers.find(c => c.id === value.customer_id)?.payment_terms || "100% предоплата");
    setComments(s?.comments || ""); setDirty(false); setReady(false); operation.current = null;
  }
  function editLine(index: number, field: keyof Line, value: string) {
    setLines(lines.map((l, i) => i === index ? {...l, [field]: value} : l)); setDirty(true);
  }
  if (loading) return <main className="login"><p>Загрузка рабочего места…</p></main>;
  if (!logged) return <main className="login"><div className="brand">П / ПРОМСНАБ</div><form className="login-card" onSubmit={e => {e.preventDefault(); void run(async () => {await api("/login", {email, password}); setMode((await api<{mode:string}>("/me")).mode); await loadLists(); setLogged(true); setPassword("");});}}>
    <span className="eyebrow">COMMERCIAL PROPOSAL ENGINE · 01</span><h1>Рабочее место<br/>менеджера</h1><p>От заявки к согласованному предложению.</p>
    <label>Email<input type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} required/></label>
    <label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required/></label>
    <button disabled={busy}>Войти в систему →</button><p className="note">Демоаккаунт создаётся командой seed. Пароль берётся из DEMO_PASSWORD.</p><p role="alert" className="error">{error}</p>
  </form><span className="mode">Синтетические данные · подтверждение менеджером</span></main>;
  return <div className="shell">
    <header><div className="brand">П / ПРОМСНАБ</div><span className="mode">{mode==="mock"?"Mock provider · без внешнего API":"LLM · проверка менеджером"}</span><button className="quiet" onClick={() => void run(async () => {await api("/logout", {}); setLogged(false); setActive(null);})}>Выйти</button></header>
    <aside><div className="aside-heading"><span>ЗАЯВКИ / {inquiries.length}</span><button className="small" disabled={busy} onClick={() => {setActive(null); setText(""); setLines([]); selectCustomer(customers[0]?.id || 1); setComments(""); setDirty(false); setReady(false); operation.current = null;}}>+ Новая</button></div>
      <nav aria-label="Заявки">{inquiries.map(i => <button disabled={busy} key={i.id} className={`inquiry ${active?.id === i.id ? "selected" : ""}`} onClick={() => void run(() => open(i.id))}><span>{i.confirmed_revision ? "● Подтверждено" : i.revision ? "◐ Черновик" : "○ Новая"}<b>{i.id.slice(0, 8)}</b></span><strong>{customers.find(c => c.id === i.customer_id)?.name}</strong><p>{i.text}</p></button>)}</nav>
    </aside>
    <main className="workspace"><div className="page-title"><div><span className="eyebrow">ПРОДАЖИ / КОММЕРЧЕСКИЕ ПРЕДЛОЖЕНИЯ</span><h1>{active ? "Предложение клиенту" : "Новая заявка"}</h1></div><span className="tag">{confirmed ? "Подтверждено" : active ? `Версия ${active.revision}` : "01 / Регистрация"}</span></div>
      <p role="alert" className={error ? "error banner" : ""}>{error}</p>
      <section className="panel"><div className="section-title"><span>01</span><h2>Клиент и запрос</h2></div><label>Компания<select value={customerId} disabled={!!active || busy} onChange={e => selectCustomerId(Number(e.target.value))}>{customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label>Обращение клиента<textarea rows={3} maxLength={20000} placeholder="Например: SKU-0001, 2 шт. Каждая позиция с новой строки." value={text} disabled={!!active || busy} onChange={e => setText(e.target.value)}/></label>
        {!active && <><label>Или загрузите XLSX / DOCX / PDF (до 10 МБ)<input type="file" accept=".xlsx,.docx,.pdf" disabled={busy} onChange={e=>setFile(e.target.files?.[0]||null)}/></label><button disabled={busy || (!text.trim()&&!file)} onClick={() => void run(async () => {
          let i:Inquiry;
          if(file){const body=new FormData();body.append("customer_id",String(customerId));body.append("text",text);body.append("file",file);i=await readResponse<Inquiry>(await fetch("/api/inquiries/import",{method:"POST",body,headers:{"Idempotency-Key":keyFor({customer_id:customerId,text,file:file.name,size:file.size,modified:file.lastModified})}}));}
          else{const payload={customer_id:customerId,text};i=await api<Inquiry>("/inquiries",payload,keyFor(payload));}
          setFile(null);await loadLists();await open(i.id);
        })}>Зарегистрировать заявку →</button></>}
        {active?.source_info?.filename && <p className="note">Исходный файл: {active.source_info.filename}. Сохранён без изменений.</p>}
        {active?.extracted_text && <details><summary>Текст исходного документа</summary><pre className="source-text">{active.extracted_text}</pre></details>}
        <p className="note">Исходный запрос сохраняется в истории. Сканированные PDF без текстового слоя требуют OCR и отправляются на ручную обработку.</p></section>
      {active && <><ProcessingPanel key={active.id} inquiry={active} onUpdated={async()=>{await open(active.id);await loadLists();}} onBusy={setProcessingBusy}/><section className="panel"><div className="section-title"><span>02</span><h2>Позиции и условия</h2></div>
        <fieldset disabled={confirmed || busy || processingBusy}><label>Поиск по каталогу<input value={query} onChange={e => setQuery(e.target.value)} placeholder="Наименование или SKU"/></label>
        <div className="catalog">{products.filter(p => `${p.name} ${p.sku}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())).slice(0, 8).map(p => <button key={p.id} className="catalog-item" onClick={() => {setLines([...lines, {product_id: p.id, quantity: "1", unit: p.unit, unit_price: p.price}]); setDirty(true);}}><div><b>{p.name}</b><small>{p.sku} · {p.stock} {p.unit} в наличии · под заказ {p.lead_days} дн.</small></div><strong>{amount(p.price)} ＋</strong></button>)}</div>
        <div className="table-wrap"><table><thead><tr><th>Позиция</th><th>Количество</th><th>Цена без НДС, ₽</th><th><span className="sr-only">Удаление</span></th></tr></thead><tbody>{lines.map((line, index) => <tr key={index}><td>{products.find(p => p.id === line.product_id)?.name}<small>{products.find(p => p.id === line.product_id)?.sku} · {line.unit}</small></td><td><input aria-label={`Количество ${index + 1}`} type="number" min="0.001" max="1000000" step="0.001" value={line.quantity} onChange={e => editLine(index, "quantity", e.target.value)}/></td><td><input aria-label={`Цена ${index + 1}`} type="number" min="0" max="100000000" step="0.01" value={line.unit_price} onChange={e => editLine(index, "unit_price", e.target.value)}/></td><td><button className="quiet" aria-label={`Удалить позицию ${index + 1}`} onClick={() => {setLines(lines.filter((_, i) => i !== index)); setDirty(true);}}>×</button></td></tr>)}</tbody></table></div>
        {!lines.length && <p className="empty">Выберите точное исполнение из каталога. Если его нет, уточните запрос у клиента.</p>}
        <div className="conditions"><label>Скидка, %<input type="number" min="0" max="100" step="0.01" value={discount} onChange={e => {setDiscount(e.target.value); setDirty(true);}}/></label><label>Условия оплаты<input maxLength={300} value={terms} onChange={e => {setTerms(e.target.value); setDirty(true);}}/></label></div><label>Комментарий менеджера<textarea rows={2} maxLength={2000} value={comments} onChange={e => {setComments(e.target.value); setDirty(true);}}/></label>
        <button disabled={!lines.length || busy} onClick={() => void run(async () => {const payload = {expected_revision: active.revision, lines, discount, payment_terms: terms, comments}; await api(`/inquiries/${active.id}/versions`, payload, keyFor(payload)); await open(active.id); await loadLists();})}>Рассчитать и сохранить версию</button></fieldset>
      </section>
      {snapshot && <section className="panel"><div className="section-title"><span>03</span><h2>Проверка и документы</h2></div><p className="note">{snapshot.number} · расчёт сервера · {dirty ? "Есть несохранённые изменения — пересчитайте КП" : "Текущая сохранённая версия"}</p>
        <div className="summary"><div><small>До скидки</small><strong>{amount(snapshot.subtotal)}</strong></div><div><small>Скидка</small><strong>{amount(snapshot.discount_amount)}</strong></div><div><small>НДС {snapshot.vat_rate}%</small><strong>{amount(snapshot.vat)}</strong></div><div className="total"><small>Итого с НДС</small><strong>{amount(snapshot.total)}</strong></div></div>
        <ul className="availability">{snapshot.lines.map((l,i) => <li key={i}>{l.sku}: {l.availability}</li>)}</ul>
        {!confirmed ? <button disabled={busy || dirty} onClick={() => void run(async () => {try {await api(`/inquiries/${active.id}/confirm`, {revision: active.revision}); setReady(true);} finally {const value = await api<Inquiry>(`/inquiries/${active.id}`); setActive(value); await loadLists();}})}>Подтвердить цены и создать DOCX / PDF</button> : <div className="downloads"><button disabled={busy} onClick={() => void run(async () => {await api(`/inquiries/${active.id}/documents`, {}); setReady(true); setActive(await api(`/inquiries/${active.id}`));})}>{ready ? "Документы готовы" : "Подготовить / повторить документы"}</button><a href={`/api/inquiries/${active.id}/files/docx`} target="_blank" rel="noreferrer">Скачать DOCX ↗</a><a href={`/api/inquiries/${active.id}/files/pdf`} target="_blank" rel="noreferrer">Скачать PDF ↗</a></div>}
        <p className="note">Подтверждение фиксирует версию и цены. Наличие справочное: товар не резервируется. Отправка клиенту не выполняется.</p>
      </section>}
      <section className="panel"><div className="section-title"><span>04</span><h2>Журнал обработки</h2></div><ol className="timeline">{active.events?.map((e,i) => <li key={i}><time>{new Date(e.at).toLocaleString("ru-RU")}</time><strong>{actionNames[e.action] || e.action}</strong><small>{e.actor}</small></li>)}</ol>{active.versions && active.versions.length > 1 && <details><summary>История версий ({active.versions.length})</summary>{active.versions.map(v => <p key={v.revision}>Версия {v.revision}: {amount(v.snapshot.total)} · {v.snapshot.comments}</p>)}</details>}</section></>}
      <footer>Промснаб / Демо · Все компании и товары вымышлены</footer>
    </main>
  </div>;
  function selectCustomerId(id: number) { selectCustomer(id); }
}
