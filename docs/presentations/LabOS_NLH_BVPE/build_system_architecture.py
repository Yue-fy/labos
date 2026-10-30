"""Build a standalone LabOS architecture figure using editable native vectors."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import zipfile
from pathlib import Path

import pymupdf
from pptx import Presentation

import build_presentation as g
from verify_english_deck import export_svg

ROOT=Path(__file__).resolve().parent/"System_Architecture"
ROOT.mkdir(exist_ok=True)
W,H=2560,1680
C=g.C


class Scene(g.Slide):
    def __init__(self):
        self.title="LabOS System Architecture"
        self.section="Distributed laboratory architecture"
        self.note=("One central LabOS server hosts scientific AI reasoning, specialist sub-agents, knowledge and memory, "
                   "and deterministic coordination. A server-side model router prefers a remote cloud model and falls back "
                   "to the server's local LLM when cloud connectivity, the API or its quota is unavailable. "
                   "The agents preserve experiment context and tool permissions across model changes. "
                   "Each instrument-host PC runs one persistent execution worker, called a PC Agent. "
                   "The worker does not require a local large language model. It owns instrument sessions, bounded adapters, "
                   "a command journal, watchdog and artifact outbox. An operator computer can use only a browser. "
                   "All laboratory PCs initiate their HTTP(S) connections; command arrows represent payload flow, "
                   "not inbound network sessions. Physical device interfaces remain local to the instrument host. "
                   "A/B retain the supplied optical and sample-lab inventory; C through N illustrate additional resource hosts. "
                   "Hardware reference and trigger cables are separate from this control network. "
                   "This figure describes the scalable LabOS system design, rather than an inventory of currently commissioned drivers.")
        self.source="Original LabOS architecture drawing, based on project design and the supplied laboratory scenario."
        self.ops=[];self.errors=[];self.dark=False
        self.rect(0,0,W,H,C["white"])


def text(s,x,y,w,h,t,size=22,color=None,bold=False,align="left"):
    s.text(x,y,w,h,t,size,color or C["ink"],bold,align,leading=1.25)


def panel(s,x,y,w,h,title,color,fill,title_size=28):
    s.rect(x,y,w,h,fill,color,radius=15,lw=1.8)
    text(s,x+22,y+18,w-44,45,title,title_size,color,True)


def monitor(s,x,y,w=65,h=48,color=None):
    color=color or C["blue"]
    s.rect(x,y,w,h,C["pale"],color,radius=4,lw=2)
    s.rect(x+7,y+7,w-14,h-14,C["white"])
    s.line(x+w/2,y+h,x+w/2,y+h+10,color,2)
    s.line(x+w*.21,y+h+12,x+w*.79,y+h+12,color,3)


def server_icon(s,x,y):
    s.rect(x,y,63,75,C["pale"],C["blue"],radius=7,lw=2)
    for k in range(3):
        yy=y+10+k*21
        s.rect(x+8,yy,47,15,C["white"],C["blue"],radius=3,lw=1)
        s.circle(x+46,yy+7.5,2.5,C["green"])
        s.line(x+14,yy+7.5,x+33,yy+7.5,C["blue"],1.5)


def database(s,x,y,w=72):
    for offset in (35,17,0):
        s.rect(x,y+offset,w,29,C["white"],C["green"],radius=10,lw=1.7)
    pts=[(x+w/2+w/2*math.cos(k*math.pi/12),y+8+8*math.sin(k*math.pi/12)) for k in range(24)]
    s.poly(pts,C["mint"],C["green"],1.5)


def card(s,x,y,w,h,title,body,color=C["teal"],fill=C["white"],title_size=22,body_size=18):
    s.rect(x,y,w,h,fill,color,radius=8,lw=1.3)
    text(s,x+12,y+10,w-24,31,title,title_size,color,True)
    if body:text(s,x+12,y+45,w-24,h-50,body,body_size)


def instrument(s,x,y,w,title,sub="",h=52):
    s.rect(x,y,w,h,C["pale"],C["blue"],radius=5,lw=1.3)
    s.rect(x+9,y+8,w-65,h-16,C["navy"],radius=3)
    size=17
    while g.width(title,size,True)>w-83:size-=.5
    text(s,x+17,y+13,w-83,26,title,size,C["white"],True)
    s.circle(x+w-30,y+h/2,10,C["white"],C["blue"],1.3)
    s.circle(x+w-11,y+h-10,2.8,C["green"])
    if sub:text(s,x+12,y+h+5,w-24,23,sub,15,C["muted"])


def build():
    s=Scene()
    text(s,60,31,1570,66,"LabOS System Architecture",47,C["navy"],True)
    text(s,62,102,1510,35,"One central server • many PCs • shared knowledge and experimental evidence",23,C["muted"])

    s.rect(1290,58,385,86,C["plum"],C["purple"],radius=13,lw=1.5,dash=True)
    text(s,1311,72,343,34,"Cloud LLM API",26,C["purple"],True,align="center")
    text(s,1311,112,343,27,"Remote model service",19,C["muted"],align="center")
    s.arrow([(1468,190),(1468,144)],C["purple"],2.3,head=9)
    s.arrow([(1496,144),(1496,190)],C["green"],2.3,head=9)

    # The operator console has no instrument worker. It is a browser client.
    s.rect(1725,64,775,88,C["sand"],C["amber"],radius=13,lw=1.8)
    monitor(s,1747,78,67,44,C["amber"])
    text(s,1840,76,637,35,"Human / operator computer",27,C["amber"],True)
    text(s,1840,115,637,27,"Browser only • question, review and authorize",20)
    s.arrow([(2112,152),(2112,190)],C["amber"],2.8,head=11)

    # Exactly one physical central server encloses all central logical services.
    s.rect(60,190,2440,655,C["bg"],C["blue"],radius=21,lw=2.8)
    server_icon(s,88,208)
    text(s,172,211,870,48,"CENTRAL LABOS SERVER",35,C["navy"],True)
    text(s,172,258,1740,29,"Scientific reasoning + deterministic control + durable evidence on one server",22,C["muted"])
    text(s,2040,218,420,33,"ONE CENTRAL ENDPOINT",21,C["blue"],True,align="right")

    panel(s,95,310,560,495,"Knowledge / memory",C["green"],C["mint"],30)
    database(s,548,330,74)
    text(s,120,379,495,29,"SEMANTIC KNOWLEDGE",20,C["green"],True)
    text(s,120,421,495,100,"Scientific literature + protocols\nInstrument manuals + local code\nCalibrations + setup definitions",22)
    s.line(120,534,629,534,"BFDCCF",1.5)
    text(s,120,552,495,29,"EXPERIMENT / EPISODIC MEMORY",20,C["green"],True)
    text(s,120,593,495,113,"Prior runs + raw artifacts\nCommands, faults + recoveries\nAnalyses + provenance\nRun / setup / capability registry",22)
    s.rect(117,719,516,64,C["white"],"BFDCCF",radius=7)
    text(s,132,729,487,24,"Retrieve → cite → reuse",20,C["green"],True)
    text(s,132,758,487,22,"Versioned records + configuration hashes",17,C["muted"])

    panel(s,720,310,1200,265,"Main AI agent / control system",C["purple"],C["plum"],32)
    text(s,744,367,1150,31,"Scientific objective → measurement strategy → evidence-based next step",22,C["purple"])
    titles=["Question + context","Review evidence","Build stage plan","Interpret + refine"]
    for i,t in enumerate(titles):
        xx=745+i*288
        s.rect(xx,424,265,66,C["white"],C["purple"],radius=9,lw=1.5)
        text(s,xx+12,444,241,31,t,22,C["purple"],True,align="center")
        if i<3:s.arrow([(xx+265,457),(xx+283,457)],C["purple"],2,head=7)
    text(s,746,520,1148,31,"Delegate specialist work • compare controls • propose the next scientific stage",21,C["purple"])
    s.arrow([(655,447),(720,447)],C["green"],2.2,head=8)
    s.arrow([(720,464),(655,464)],C["green"],2.2,head=8)
    text(s,661,412,54,28,"RAG",18,C["green"],True,align="center")

    panel(s,1970,310,495,265,"Specialist sub-agents",C["purple"],C["plum"],27)
    for i,t in enumerate(["Literature / protocols","Planning / sequencing","Analysis / fitting","Interpretation / controls","Troubleshooting","Code / adapter review"]):
        yy=367+i*31
        s.rect(1992,yy,451,26,C["white"],"C9B9EA",radius=5,lw=1)
        text(s,2006,yy+2,424,25,t,18,C["purple"])
    s.arrow([(1920,428),(1970,428)],C["purple"],2.2,head=8)
    s.arrow([(1970,448),(1920,448)],C["purple"],2.2,head=8)

    # Scientific proposals and observed evidence cross a deterministic boundary.
    s.arrow([(1040,575),(1040,640)],C["purple"],2.8,head=11)
    text(s,1063,594,393,31,"Stage proposal",21,C["purple"],True)
    s.arrow([(1550,640),(1550,575)],C["green"],2.8,head=11)
    text(s,1573,594,340,31,"Qualified evidence",21,C["green"],True)
    panel(s,720,640,1200,165,"Deterministic execution coordinator",C["teal"],C["ice"],28)
    for i,t in enumerate(["Schema + units","Limits + resource locks","Stage / point barriers","Command / data ledger"]):
        xx=742+i*290
        s.rect(xx,708,274,53,C["white"],C["teal"],radius=7,lw=1.3)
        text(s,xx+9,726,256,26,t,18,C["teal"],True,align="center")
    text(s,744,776,1152,24,"Per-PC identity • deadlines • cancellation • qualification • exclusive device ownership",18,C["teal"])
    s.arrow([(720,724),(655,724)],C["green"],2.2,head=8)
    text(s,660,687,56,27,"Save",17,C["green"],True,align="center")

    panel(s,1970,640,495,165,"Model router / failover",C["purple"],C["plum"],25)
    text(s,1994,696,448,92,"Preferred: cloud model API\nFallback: local LLM on this server\nTriggers: API / internet / quota\nContext + permissions preserved",18)
    s.arrow([(1920,504),(1940,504),(1940,620),(2100,620),(2100,640)],C["purple"],2,head=8)
    s.arrow([(2330,640),(2330,600),(1955,600),(1955,480),(1920,480)],C["purple"],2,head=8)

    # Network buses show payload directions, while every PC initiates HTTP(S).
    text(s,61,866,1050,38,"NETWORK  •  HTTP(S) OVER LAN / VPN",25,C["navy"],True)
    text(s,1630,866,870,34,"PC-initiated connections • no SSH dependency",21,C["muted"],align="right")
    s.arrow([(1160,805),(1160,930)],C["purple"],2.8,head=10)
    s.arrow([(1560,982),(1560,805)],C["green"],2.8,head=10)
    s.line(241,930,2291,930,C["purple"],3)
    s.line(269,982,2319,982,C["green"],3)
    text(s,61,914,170,31,"Commands ↓",20,C["purple"],True)
    text(s,61,968,198,31,"Evidence ↑",20,C["green"],True)
    text(s,1630,895,870,27,"Register / heartbeat / poll / results / artifacts",18,C["muted"],align="right")

    pcs=[("PC A","Optical lab","SuperK + IR spectroscopy","Vendor SDK / USB / LAN"),
         ("PC B","Sample lab","Environment + electrical / optical","SDK / VISA / serial"),
         ("PC C","Imaging lab","Microscopy + camera acquisition","Camera SDK / USB / LAN"),
         ("PC D","Motion lab","Positioning + sample alignment","USB / serial / Ethernet"),
         ("PC E","Electrical lab","Source + readout resources","VISA / GPIB / serial"),
         ("PC N","Additional lab","Expandable instrument resources","Driver-specific interfaces")]
    for i,(name,role,sub,protocol) in enumerate(pcs):
        x=60+i*410;cx=x+195
        s.arrow([(cx-14,930),(cx-14,1040)],C["purple"],2,head=8)
        s.arrow([(cx+14,1040),(cx+14,982)],C["green"],2,head=8)
        s.circle(cx-14,930,3.7,C["purple"]);s.circle(cx+14,982,3.7,C["green"])
        s.rect(x,1040,390,265,C["ice"],C["teal"],radius=13,lw=1.8)
        monitor(s,x+18,1057,62,44,C["teal"])
        text(s,x+97,1058,276,35,f"{name} / {role}",23,C["teal"],True)
        text(s,x+97,1098,276,25,sub,16,C["muted"])
        card(s,x+18,1135,354,64,"Local PC Agent","",C["teal"],C["white"],23)
        text(s,x+31,1175,328,24,"Persistent execution worker",17,C["muted"])
        s.arrow([(cx,1199),(cx,1217)],C["teal"],1.8,head=7)
        s.rect(x+18,1217,354,68,C["white"],C["teal"],radius=8,lw=1.2)
        text(s,x+30,1227,330,26,"Driver adapters + sessions",20,C["teal"],True)
        text(s,x+30,1260,330,25,"Journal • watchdog • raw-data outbox",16,C["green"])
        s.arrow([(x+34,1305),(x+34,1360)],C["blue"],2.3,head=9)
        s.arrow([(x+48,1360),(x+48,1305)],C["blue"],2.3,head=9)
        text(s,x+59,1321,319,27,protocol,17,C["blue"])
        s.rect(x,1360,390,215,C["bg"],C["blue"],radius=11,lw=1.5)
        text(s,x+18,1373,354,26,"PHYSICAL DEVICES",18,C["blue"],True)
        if i==0:
            instrument(s,x+18,1410,354,"SuperK",h=58)
            instrument(s,x+18,1491,354,"IR spectrometer",h=58)
        elif i==1:
            instrument(s,x+18,1407,354,"attoDRY + transport lock-ins ×2",h=40)
            instrument(s,x+18,1456,354,"BVPE lock-in / chopper / PD",h=40)
            instrument(s,x+18,1505,354,"730 nm / CLD1000 / 2400",h=40)
            text(s,x+20,1549,349,25,"Motorized polarizer / QWP",17,C["muted"])
        elif i==2:
            # Camera above an objective and sample plane.
            s.rect(x+144,1410,100,48,C["pale"],C["blue"],radius=6,lw=2)
            s.circle(x+194,1434,14,C["white"],C["blue"],2)
            s.poly([(x+163,1458),(x+225,1458),(x+213,1500),(x+175,1500)],C["pale"],C["blue"],2)
            s.arrow([(x+194,1500),(x+194,1518)],C["blue"],1.6,head=6)
            s.rect(x+119,1523,152,9,C["blue"],radius=2)
            text(s,x+18,1540,354,28,"Microscope / camera",20,C["blue"],True,align="center")
        elif i==3:
            for dx,dy in [(0,0),(22,-15),(44,-30)]:
                s.rect(x+102+dx,1470+dy,145,30,C["pale"],C["blue"],radius=3,lw=1.6)
            s.arrow([(x+127,1430),(x+255,1430)],C["purple"],2,head=8)
            s.arrow([(x+277,1510),(x+277,1410)],C["teal"],2,head=8)
            text(s,x+18,1540,354,28,"Stages / motors / encoders",19,C["blue"],True,align="center")
        elif i==4:
            instrument(s,x+18,1410,354,"Current / voltage source",h=58)
            instrument(s,x+18,1491,354,"Meter / lock-in / digitizer",h=58)
        else:
            instrument(s,x+18,1410,354,"Instrument / controller",h=58)
            instrument(s,x+18,1491,354,"Detector / sensor",h=58)

    s.line(60,1600,2500,1600,C["line"],1.5)
    text(s,60,1612,1460,26,"Server: cloud / local LLM routing. Instrument PCs: execution workers; no PC-side LLM required.",21,C["navy"],True)
    text(s,60,1646,1740,24,"A/B retain the supplied setup; C…N illustrate additional hosts. Hardware trigger / reference wiring is separate from HTTP(S).",18,C["muted"])
    text(s,1830,1613,670,28,"One experiment → coordinated stages across PCs",20,C["teal"],True,align="right")
    text(s,1840,1646,660,25,"Original LabOS system-design figure • scalable deployment view",17,C["muted"],align="right")
    return s


def verify(scene,pptx,pdf):
    errors=list(scene.errors);bounds=[]
    prs=Presentation(pptx);doc=pymupdf.open(pdf)
    assert len(prs.slides)==len(doc)==1
    ptext="\n".join(sh.text for sh in prs.slides[0].shapes if sh.has_text_frame)
    pdftext=doc[0].get_text()
    assert ptext.count("CENTRAL LABOS SERVER")==1
    assert ptext.count("Local PC Agent")==6
    assert ptext.count("Human / operator computer")==1
    assert "Model router / failover" in ptext and "Fallback: local LLM on this server" in ptext
    for name in ["PC A","PC B","PC C","PC D","PC E","PC N"]:assert f"{name} / " in ptext
    norm=lambda t:re.sub(r"\s+","",t)
    for oi,o in enumerate(scene.ops):
        if o["kind"]!="text":continue
        for j,line in enumerate(o["lines"]):
            if norm(line) not in norm(ptext):errors.append(f"Missing PPTX text: {line}")
            if norm(line) not in norm(pdftext):errors.append(f"Missing PDF text: {line}")
            tw=g.width(line,o["size"],o["bold"])
            xx=o["x"]+((o["w"]-tw)/2 if o["align"]=="center" else o["w"]-tw if o["align"]=="right" else 0)
            yy=o["y"]+j*o["size"]*o["leading"]
            if line:bounds.append((oi,line,(xx,yy,xx+tw,yy+o["size"])))
    for i,a in enumerate(bounds):
        for b in bounds[i+1:]:
            if a[0]==b[0]:continue
            ax,ay,ar,ab=a[2];bx,by,br,bb=b[2]
            if min(ar,br)-max(ax,bx)>8 and min(ab,bb)-max(ay,by)>5:
                errors.append(f"Text overlap: {a[1]} / {b[1]}")
    for block in doc[0].get_text("dict")["blocks"]:
        for line in block.get("lines",[]):
            for span in line["spans"]:
                x0,y0,x1,y1=span["bbox"]
                if min(x0,y0)<0 or x1>W*.5+1 or y1>H*.5+1:errors.append(f"PDF text outside page: {span['text']}")
    assert not re.search(r"[\u3400-\u9fff]",ptext+prs.slides[0].notes_slide.notes_text_frame.text)
    assert not any(int(sh.shape_type)==13 for sh in prs.slides[0].shapes)
    if errors:raise AssertionError("\n".join(errors))
    return dict(status="PASS",pages=1,central_servers=1,instrument_host_pcs=6,operator_browser_pcs=1,
                local_pc_agents=6,pc_local_llm_required=False,language="English",raster_images_in_pptx=0,
                server_local_llm_fallback=True,
                native_objects=len(prs.slides[0].shapes),missing_text=0,out_of_page_text=0,text_overlaps=0)


def main():
    g.W=W;g.H=H;g.SCALE=.5;g.ROOT=ROOT;g.SLIDES.clear()
    scene=build();g.SLIDES.append(scene)
    if scene.errors:raise AssertionError("\n".join(scene.errors))
    title="LabOS System Architecture: One Server, Many Instrument PCs"
    pptx=g.render_pptx("LabOS_System_Architecture_EN.pptx",title,"Central AI agents and distributed execution workers",notes_source_label="Reference: ")
    pdf=g.render_pdf("LabOS_System_Architecture_EN.pdf",title)
    record=dict(title=scene.title,section=scene.section,note=scene.note,source=scene.source,ops=scene.ops)
    (ROOT/"architecture_scene.json").write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n")
    export_svg(record,ROOT/"LabOS_System_Architecture_EN.svg",(0,0,W,H))
    report=verify(scene,pptx,pdf)
    subprocess.run(["pdftoppm","-singlefile","-scale-to","5120","-png",str(pdf),str(ROOT/"LabOS_System_Architecture_EN")],check=True,capture_output=True)
    subprocess.run(["pdftoppm","-singlefile","-scale-to","2000","-png",str(pdf),str(ROOT/"Architecture_Preview")],check=True,capture_output=True)
    (ROOT/"QA_Report.json").write_text(json.dumps(report,indent=2)+"\n")
    files=sorted(p for p in ROOT.iterdir() if p.is_file() and p.name not in {"SHA256SUMS","LabOS_System_Architecture_EN_Bundle.zip"})
    (ROOT/"SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files))
    bundle=ROOT/"LabOS_System_Architecture_EN_Bundle.zip"
    with zipfile.ZipFile(bundle,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for p in files+[ROOT/"SHA256SUMS"]:z.write(p,p.name)
    with zipfile.ZipFile(bundle) as z:
        assert z.testzip() is None
        for p in files:assert z.read(p.name)==p.read_bytes()
    print(json.dumps(report,indent=2));print(f"Bundle integrity: PASS ({len(files)+1} files)")


if __name__=="__main__":main()
