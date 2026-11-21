"""
Web app demo - Agente Foundry (tenant del curso)
Ejecutar:  python app.py   ->  http://localhost:8000
"""
import json
import os
import re

import uvicorn
from azure.ai.projects import AIProjectClient
from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    InteractiveBrowserCredential,
)
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import db
import motor

load_dotenv()
db.crear_bd()  # crea clientes.db con los 10 clientes ficticios si no existe

TENANT_ID = os.getenv("AZURE_TENANT_ID", "b08b1013-a1e1-4bf0-b7d9-67a9e6231df4")
PROJECT_ENDPOINT = os.getenv(
    "PROJECT_ENDPOINT",
    "https://fnd-caja-lab-cus-001.services.ai.azure.com/api/projects/proj-default",
)
AGENT_NAME = os.getenv("AGENT_NAME", "dictamen-credito")

# Usa 'az login' si existe; si no, abre el navegador para iniciar sesión
credential = ChainedTokenCredential(
    AzureCliCredential(tenant_id=TENANT_ID),
    InteractiveBrowserCredential(tenant_id=TENANT_ID),
)
project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
openai_client = project.get_openai_client()

app = FastAPI(title="Demo Agente Foundry")


class ChatIn(BaseModel):
    message: str
    conversation_id: str | None = None


@app.post("/chat")
def chat(body: ChatIn):
    try:
        conv_id = body.conversation_id
        if not conv_id:
            conv_id = openai_client.conversations.create().id
        resp = openai_client.responses.create(
            conversation=conv_id,
            input=body.message,
            extra_body={"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
        )
        return {"reply": resp.output_text, "conversation_id": conv_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------- evaluación por DNI
CAMPOS_EXPEDIENTE = [
    "dni", "nombre", "tipo_negocio", "distrito", "ventas_mensuales", "deuda_total", "dias_atraso",
    "antiguedad_anios", "score", "monto_solicitado", "plazo_meses", "destino", "garantia",
]


class EvaluarIn(BaseModel):
    dni: str
    conversation_id: str | None = None


def armar_datos(cliente: dict, resultado: dict) -> str:
    expediente = {k: cliente[k] for k in CAMPOS_EXPEDIENTE}
    expediente["cuota_estimada"] = resultado["cuota_estimada"]
    expediente["tea_referencial"] = resultado["tea_referencial"]
    fuentes = (
        [f"REGLA {r['codigo']}" for r in resultado["reglas"]]
        + [f"EXPEDIENTE.{k}" for k in expediente]
        + [f"RECIBO {r['id']}" for r in cliente["recibos"]]
    )
    bloque = {
        "DECISION_MOTOR": resultado["decision"],
        "REGLAS": resultado["reglas"],
        "EXPEDIENTE": expediente,
        "RECIBOS": cliente["recibos"],
        "FUENTES_VALIDAS_PARA_CITAR": fuentes,
    }
    return "<datos>\n" + json.dumps(bloque, ensure_ascii=False, indent=2) + "\n</datos>"


@app.get("/clientes")
def clientes():
    return db.listar_clientes()


@app.post("/evaluar")
def evaluar(body: EvaluarIn):
    dni = body.dni.strip()
    if not re.fullmatch(r"\d{8}", dni):
        raise HTTPException(status_code=422, detail="El DNI debe tener 8 dígitos.")
    cliente = db.buscar_cliente(dni)
    if cliente is None:
        raise HTTPException(status_code=404, detail=f"No existe un cliente con DNI {dni}.")
    resultado = motor.evaluar(cliente)
    datos = armar_datos(cliente, resultado)
    try:
        conv_id = body.conversation_id or openai_client.conversations.create().id
        resp = openai_client.responses.create(
            conversation=conv_id,
            input=datos,
            extra_body={"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al llamar al agente: {e}")
    try:
        dictamen = json.loads(resp.output_text)
    except (TypeError, ValueError):
        dictamen = None
    coincide = bool(dictamen) and dictamen.get("decision") == resultado["decision"]
    return {
        "cliente": cliente,
        "motor": resultado,
        "datos": datos,
        "dictamen": dictamen,
        "reply": resp.output_text,
        "decision_coincide": coincide,  # el agente no debe cambiar la decisión del motor
        "conversation_id": conv_id,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML.replace("{{AGENT}}", AGENT_NAME)


HTML = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo Agente Foundry</title>
<style>
 *{box-sizing:border-box} html,body{height:100%}
 body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#f3f4f6;color:#111;display:flex}
 aside{width:260px;background:#1f1235;color:#e9e3f5;display:flex;flex-direction:column;flex-shrink:0}
 aside .top{padding:14px}
 #nuevo{width:100%;background:#5b21b6;color:#fff;border:0;border-radius:8px;padding:10px;cursor:pointer;font:inherit}
 aside h5{margin:6px 14px;font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:#a89bc2}
 #lista{flex:1;overflow-y:auto;padding:0 8px 12px}
 .conv{display:flex;align-items:center;gap:6px;padding:8px 10px;border-radius:8px;cursor:pointer;font-size:14px}
 .conv:hover{background:#2e1d4d} .conv.activa{background:#3b2763}
 .conv .tit{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .conv .del{opacity:0;background:none;border:0;color:#c4b5fd;cursor:pointer;font-size:14px;padding:0 4px}
 .conv:hover .del{opacity:1}
 .vacio{font-size:13px;color:#8b7fa6;padding:8px 10px}
 main{flex:1;display:flex;flex-direction:column;min-width:0}
 header{background:#5b21b6;color:#fff;padding:14px 20px} header small{opacity:.8}
 #chat{flex:1;overflow-y:auto;padding:20px}
 #chat>*{max-width:820px;margin-left:auto;margin-right:auto}
 .fila{display:flex} .fila.u{justify-content:flex-end}
 .msg{padding:10px 14px;border-radius:10px;margin:8px 0;white-space:pre-wrap;max-width:85%;line-height:1.45}
 .user{background:#5b21b6;color:#fff} .bot{background:#fff;border:1px solid #e5e7eb}
 .err{background:#fee2e2;border:1px solid #fca5a5}
 .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;margin:8px 0;max-width:85%;overflow:hidden}
 .card-head{display:flex;align-items:center;gap:12px;padding:14px 16px;border-left:6px solid var(--c)}
 .badge{background:var(--c);color:#fff;font-weight:700;padding:6px 14px;border-radius:999px;font-size:15px;letter-spacing:.5px;white-space:nowrap}
 .resumen{font-size:14px;color:#374151}
 .sec{padding:10px 16px;border-top:1px solid #f3f4f6}
 .sec h4{margin:0 0 6px;font-size:12px;text-transform:uppercase;color:#6b7280;letter-spacing:.6px}
 .sec ul{margin:0;padding-left:18px} .sec li{margin:4px 0;line-height:1.4;font-size:14px}
 .cod{font-family:Consolas,monospace;font-size:11px;background:#f3f4f6;padding:1px 6px;border-radius:4px;margin-right:6px;color:#4b5563}
 .cita{font-size:12px;color:#6b7280;margin-top:2px}
 details{padding:8px 16px;border-top:1px solid #f3f4f6;font-size:12px;color:#6b7280}
 details pre{white-space:pre-wrap;font-size:11px;background:#f9fafb;padding:8px;border-radius:6px}
 form{display:flex;gap:8px;padding:12px 20px 18px;max-width:860px;width:100%;margin:0 auto}
 textarea{flex:1;padding:10px;border-radius:8px;border:1px solid #d1d5db;font:inherit;resize:none;height:52px}
 #b{background:#5b21b6;color:#fff;border:0;border-radius:8px;padding:0 18px;cursor:pointer}
 #b:disabled{opacity:.5}
 .aviso{background:#fef3c7;border:1px solid #fcd34d}
 .ficha .card-head{border-left-color:#5b21b6;flex-wrap:wrap}
 .ficha .nom{font-weight:700;font-size:15px} .ficha .sub{font-size:13px;color:#6b7280}
 .kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px 16px;padding:10px 16px;border-top:1px solid #f3f4f6}
 .kv small{display:block;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px}
 .kv b{font-size:14px;font-weight:600}
 .regla{list-style:none;margin-left:-18px!important;display:flex;gap:8px;align-items:baseline}
 .regla .ic{font-weight:700;width:14px} .ok{color:#16a34a} .no{color:#dc2626}
 .regla .um{font-size:12px;color:#6b7280}
 .tag{font-size:11px;padding:1px 6px;border-radius:4px;background:#f3f4f6;color:#6b7280}
</style></head><body>
<aside>
 <div class="top"><button id="nuevo">+ Nueva conversación</button></div>
 <h5>Recientes</h5>
 <div id="lista"></div>
</aside>
<main>
 <header><b>Demo Agente Foundry</b> &nbsp;<small>agente: {{AGENT}}</small></header>
 <div id="chat"></div>
 <form id="f"><textarea id="t" placeholder="Escribe: evalúa el DNI 45128763  (o pregunta sobre el dictamen)"></textarea><button id="b">Enviar</button></form>
</main>
<script>
const KEY='foundry_convs_{{AGENT}}';
const chat=document.getElementById('chat'),t=document.getElementById('t'),b=document.getElementById('b'),lista=document.getElementById('lista');
let convs=cargar(); let actual=null; // actual = id local de la conversación abierta

function cargar(){try{return JSON.parse(localStorage.getItem(KEY))||[];}catch(e){return [];}}
function guardar(){try{localStorage.setItem(KEY,JSON.stringify(convs));}catch(e){}}
function getConv(id){return convs.find(c=>c.id===id);}

function el(tag,cls,txt){const e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}
function aTexto(v){return typeof v==='string'?v:JSON.stringify(v);}
function parseJSON(txt){
 const limpio=String(txt).replace(/^\s*```(?:json)?/i,'').replace(/```\s*$/,'').trim();
 try{const o=JSON.parse(limpio);return (o&&typeof o==='object')?o:null;}catch(e){return null;}
}
function color(dec){
 if(/^APROB|^APRUEB/.test(dec))return '#16a34a';
 if(/^RECHAZ|^DENEG/.test(dec))return '#dc2626';
 if(/^RESERV|^OBSERV|^PENDIENT/.test(dec))return '#d97706';
 return '#6b7280';
}
function titulo(txt){
 const m=txt.match(/Cliente:\s*([^\n]+)/i);
 const base=m?m[1]:txt.replace(/<\/?datos>/gi,'').trim().split('\n')[0];
 return base.slice(0,40)||'Conversación';
}

function tarjeta(o){
 const dec=String(o.decision||'SIN DECISIÓN').toUpperCase();
 const card=el('div','card');card.style.setProperty('--c',color(dec));
 const motivos=Array.isArray(o.motivos)?o.motivos:[];
 const recs=Array.isArray(o.recomendaciones)?o.recomendaciones:[];
 const head=el('div','card-head');head.appendChild(el('span','badge',dec));
 const primera=motivos[0]&&(motivos[0].explicacion||aTexto(motivos[0]));
 head.appendChild(el('span','resumen',primera?primera.split('. ')[0].replace(/\.$/,'')+'.':''));
 card.appendChild(head);
 if(motivos.length){
  const s=el('div','sec');s.appendChild(el('h4',null,'Motivos'));const ul=el('ul');
  motivos.forEach(m=>{const li=el('li');
   if(m.codigo)li.appendChild(el('span','cod',m.codigo));
   li.appendChild(document.createTextNode(m.explicacion||aTexto(m)));
   if(Array.isArray(m.citas)&&m.citas.length)li.appendChild(el('div','cita','Fuente: '+m.citas.map(aTexto).join('; ')));
   ul.appendChild(li);});
  s.appendChild(ul);card.appendChild(s);
 }
 if(recs.length){
  const s=el('div','sec');s.appendChild(el('h4',null,'Qué hacer ahora'));const ul=el('ul');
  recs.forEach(r=>ul.appendChild(el('li',null,aTexto(r))));s.appendChild(ul);card.appendChild(s);
 }
 if(o.recibos&&o.recibos.detalle){
  const s=el('div','sec');s.appendChild(el('h4',null,'Recibos'));
  s.appendChild(el('div','resumen',aTexto(o.recibos.detalle)));card.appendChild(s);
 }
 const det=el('details');det.appendChild(el('summary',null,'Ver JSON completo'));
 det.appendChild(el('pre',null,JSON.stringify(o,null,2)));card.appendChild(det);
 return card;
}

function soles(n){return 'S/ '+Number(n).toLocaleString('es-PE',{minimumFractionDigits:2,maximumFractionDigits:2});}
function ficha(d){
 const c=d.cliente,m=d.motor,card=el('div','card ficha');
 const head=el('div','card-head');
 const id=el('div');id.appendChild(el('div','nom',c.nombre));
 id.appendChild(el('div','sub','DNI '+c.dni+' · '+c.tipo_negocio+' · '+c.distrito+', Piura'));
 head.appendChild(id);card.appendChild(head);
 const kv=el('div','kv');
 [['Ventas mensuales',soles(c.ventas_mensuales)],['Deuda total',soles(c.deuda_total)],
  ['Atraso en centrales',c.dias_atraso+' días'],['Antigüedad',c.antiguedad_anios+' años'],['Score',c.score],
  ['Monto solicitado',soles(c.monto_solicitado)],['Plazo',c.plazo_meses+' meses'],
  ['Cuota estimada',soles(m.cuota_estimada)+' (TEA '+Math.round(m.tea_referencial*100)+' %)'],
  ['Destino',c.destino],['Garantía',c.garantia]]
  .forEach(([k,v])=>{const x=el('div');x.appendChild(el('small',null,k));x.appendChild(el('b',null,String(v)));kv.appendChild(x);});
 card.appendChild(kv);
 const s=el('div','sec');const h=el('h4',null,'Motor de reglas → ');
 const bdg=el('span','badge',m.decision);bdg.style.cssText='background:'+color(m.decision)+';font-size:11px;padding:2px 10px';
 h.appendChild(bdg);s.appendChild(h);const ul=el('ul');
 m.reglas.forEach(r=>{const li=el('li','regla');
  li.appendChild(el('span','ic '+(r.cumple?'ok':'no'),r.cumple?'✓':'✗'));
  li.appendChild(el('span','cod',r.codigo));
  li.appendChild(el('span',null,r.nombre+': '+r.valor));
  li.appendChild(el('span','um','(umbral '+r.umbral+')'));
  li.appendChild(el('span','tag',r.tipo));ul.appendChild(li);});
 s.appendChild(ul);card.appendChild(s);
 const sr=el('div','sec');sr.appendChild(el('h4',null,'Recibos presentados'));
 if(!c.recibos.length)sr.appendChild(el('div','resumen','Ninguno'));
 else{const u=el('ul');c.recibos.forEach(r=>{const li=el('li');li.appendChild(el('span','cod',r.id));
  li.appendChild(document.createTextNode(r.descripcion+' — '+soles(r.monto)+' ('+r.fecha+')'));
  li.appendChild(el('span','tag',r.tipo));u.appendChild(li);});sr.appendChild(u);}
 card.appendChild(sr);
 return card;
}

function pintarMensaje(m){
 const fila=el('div','fila'+(m.role==='user'?' u':''));
 if(m.role==='user')fila.appendChild(el('div','msg user',m.text));
 else if(m.role==='cliente')fila.appendChild(ficha(m.data));
 else if(m.role==='aviso')fila.appendChild(el('div','msg aviso','⚠ '+m.text));
 else if(m.role==='error')fila.appendChild(el('div','msg err','Error: '+m.text));
 else{const o=parseJSON(m.text);fila.appendChild(o?tarjeta(o):el('div','msg bot',m.text));}
 chat.appendChild(fila);chat.scrollTop=chat.scrollHeight;return fila;
}

function pintarLista(){
 lista.innerHTML='';
 if(!convs.length){lista.appendChild(el('div','vacio','Aún no hay conversaciones'));return;}
 convs.forEach(c=>{
  const d=el('div','conv'+(c.id===actual?' activa':''));
  d.appendChild(el('span','tit',c.titulo));
  const x=el('button','del','✕');x.title='Eliminar';
  x.onclick=e=>{e.stopPropagation();convs=convs.filter(k=>k.id!==c.id);guardar();if(actual===c.id)nueva();else pintarLista();};
  d.appendChild(x);d.onclick=()=>abrir(c.id);lista.appendChild(d);
 });
}

function abrir(id){actual=id;chat.innerHTML='';getConv(id).mensajes.forEach(pintarMensaje);pintarLista();t.focus();}
function bienvenida(){
 pintarMensaje({role:'bot',text:'Hola, soy el agente de dictamen de crédito. Escríbeme algo como:\n  "Evalúa el DNI 45128763"\ny busco al cliente, corro el motor de reglas y te doy el dictamen. Después puedes preguntarme sobre el resultado.'});
}
function nueva(){actual=null;chat.innerHTML='';bienvenida();pintarLista();t.focus();}

let DNIS=[];
function bloquear(v){b.disabled=v;}

// ---- Evaluación por DNI: cliente (SQLite) -> motor de reglas -> agente
async function evaluarDNI(dni,textoUsuario,enNueva){
 let c=!enNueva&&actual&&getConv(actual);
 const recien=!c;
 if(!c){c={id:String(Date.now()),titulo:'DNI '+dni,conversation_id:null,mensajes:[]};convs.unshift(c);actual=c.id;chat.innerHTML='';}
 const u={role:'user',text:textoUsuario};c.mensajes.push(u);guardar();pintarLista();pintarMensaje(u);
 bloquear(true);
 const espera=pintarMensaje({role:'bot',text:'Buscando al cliente con DNI '+dni+', corriendo el motor de reglas y redactando el dictamen...'});
 const nuevos=[];
 try{
  const r=await fetch('/evaluar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dni,conversation_id:c.conversation_id})});
  const j=await r.json();
  if(r.status===404){
   nuevos.push({role:'bot',text:'No encontré ningún cliente con DNI '+dni+' en la base de datos.'+(DNIS.length?'\nDNI disponibles para probar:\n'+DNIS.join('\n'):'')});
  }else if(!r.ok){throw new Error(typeof j.detail==='string'?j.detail:'HTTP '+r.status);}
  else{
   if(recien)c.titulo=j.cliente.nombre+' · '+dni;
   c.conversation_id=j.conversation_id;
   nuevos.push({role:'cliente',data:{cliente:j.cliente,motor:j.motor}});
   if(j.dictamen&&!j.decision_coincide)
    nuevos.push({role:'aviso',text:'El agente devolvió "'+j.dictamen.decision+'" pero el motor decidió "'+j.motor.decision+'". Prevalece la decisión del motor.'});
   nuevos.push({role:'bot',text:j.reply});
  }
 }catch(err){nuevos.push({role:'error',text:err.message});}
 espera.remove();c.mensajes.push(...nuevos);
 if(actual===c.id)nuevos.forEach(pintarMensaje);
 convs=[c,...convs.filter(k=>k.id!==c.id)];guardar();pintarLista();bloquear(false);t.focus();
}

document.getElementById('nuevo').onclick=nueva;
t.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();document.getElementById('f').requestSubmit();}});
document.getElementById('f').onsubmit=async e=>{
 e.preventDefault();const m=t.value.trim();if(!m)return;
 // Si el mensaje trae un DNI (8 dígitos) y no es un bloque <datos>, se evalúa ese cliente
 const dm=!/<datos>/i.test(m)&&m.match(/(?<!\d)\d{8}(?!\d)/);
 if(dm){t.value='';return evaluarDNI(dm[0],m,false);}
 let c=actual&&getConv(actual);
 if(!c){c={id:String(Date.now()),titulo:titulo(m),conversation_id:null,mensajes:[]};convs.unshift(c);actual=c.id;chat.innerHTML='';}
 c.mensajes.push({role:'user',text:m});guardar();pintarLista();
 pintarMensaje({role:'user',text:m});t.value='';bloquear(true);
 const espera=pintarMensaje({role:'bot',text:'Pensando...'});
 try{
  const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m,conversation_id:c.conversation_id})});
  const j=await r.json();
  if(!r.ok)throw new Error(j.detail||r.status);
  c.conversation_id=j.conversation_id;c.mensajes.push({role:'bot',text:j.reply});
  espera.remove();if(actual===c.id)pintarMensaje({role:'bot',text:j.reply});
 }catch(err){c.mensajes.push({role:'error',text:err.message});espera.remove();if(actual===c.id)pintarMensaje({role:'error',text:err.message});}
 // mover la conversación usada al inicio de la lista
 convs=[c,...convs.filter(k=>k.id!==c.id)];guardar();pintarLista();
 bloquear(false);t.focus();
};

fetch('/clientes').then(r=>r.json()).then(l=>{DNIS=l.map(k=>k.dni+' — '+k.nombre+' ('+k.tipo_negocio+')');}).catch(()=>{});
bienvenida();pintarLista();
</script></body></html>"""


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)