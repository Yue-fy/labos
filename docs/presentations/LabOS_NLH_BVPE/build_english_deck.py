"""Detailed English technical presentation: native editable vectors in PPTX and PDF."""
from __future__ import annotations

import json
from pathlib import Path

import build_presentation as g

C=g.C
OUT=Path(__file__).resolve().parent/"English"
OUT.mkdir(exist_ok=True)
g.ROOT=OUT
g.SLIDES.clear()


class EnglishSlide(g.Slide):
    def text(self,x,y,w,h,text,size=22,color=None,bold=False,align="left",leading=1.35):
        # Preserve every word and all geometry; choose a fitting, explicit font size.
        text=text.replace("fI","f_I")
        while len(g.wrap(text,w,size,bold))*size*leading>h+2 and size>11.5:
            size-=.5
        super().text(x,y,w,h,text,size,color,bold,align,leading)

    def box(self,x,y,w,h,title,body="",accent=None,fill=None,size=21,title_size=24):
        if h>=120:
            return super().box(x,y,w,h,title,body,accent,fill,size,title_size)
        accent=accent or C["teal"]
        self.rect(x,y,w,h,fill or C["white"],C["line"],radius=11)
        self.rect(x,y+16,4,31,accent)
        self.text(x+20,y+12,w-40,34,title,title_size,accent,True)
        if body:self.text(x+20,y+50,w-40,h-56,body,size,C["ink"])


g.Slide=EnglishSlide


def new(section,title,subtitle="",note="",source="",dark=False):
    return g.add(section,title,subtitle,note=note,source=source,dark=dark)


def label(s,x,y,w,text,size=17,color=None,bold=False,h=29,align="left"):
    s.text(x,y,w,h,text,size,color or C["ink"],bold,align)


def region(s,x,y,w,h,title,color=None,fill=None):
    color=color or C["teal"]
    s.rect(x,y,w,h,fill or C["white"],color,radius=11,lw=1.2)
    label(s,x+13,y+10,w-26,title,20,color,True,h=34)


def instrument(s,x,y,w,h,title,screen,ports=(),color=None):
    color=color or C["teal"]
    s.rect(x,y,w,h,C["white"],color,radius=7,lw=1.4)
    label(s,x+10,y+7,w-20,title,17,color,True,h=29)
    s.rect(x+10,y+39,w-54,max(22,h-67),C["bg"],C["line"],radius=3)
    label(s,x+16,y+43,w-69,screen,13,C["ink"],h=max(24,h-72))
    s.circle(x+w-23,y+51,9,C["pale"],color,1.2)
    s.circle(x+w-23,y+76,4,C["green"])
    if ports:
        step=(w-20)/len(ports)
        for i,p in enumerate(ports):
            px=x+10+(i+.5)*step
            s.circle(px,y+h-12,3.3,color)
            label(s,px-step/2,y+h+3,step,p,11,C["muted"],h=19,align="center")


def cryostat(s,x,y,w=190,h=250):
    # A schematic optical-access cryostat, not a vendor CAD drawing.
    s.rect(x,y+20,w,h-40,C["pale"],C["blue"],radius=24,lw=2)
    s.rect(x+15,y+3,w-30,35,C["white"],C["blue"],radius=13,lw=1.7)
    s.rect(x+15,y+h-28,w-30,35,C["white"],C["blue"],radius=13,lw=1.7)
    s.rect(x+w*.29,y+43,w*.42,h-90,C["white"],C["line"],radius=10)
    for yy in (y+h*.39,y+h*.6):
        s.rect(x+18,yy-14,w*.23,28,"CCDDF2",C["blue"],radius=4)
        s.rect(x+w*.67,yy-14,w*.23,28,"CCDDF2",C["blue"],radius=4)
        for i in range(4):
            s.line(x+21+i*7,yy-11,x+21+i*7,yy+11,C["blue"],.8)
            s.line(x+w*.69+i*7,yy-11,x+w*.69+i*7,yy+11,C["blue"],.8)
    s.arrow([(x+w*.49,y+h*.72),(x+w*.49,y+h*.29)],C["purple"],1.6,head=6)
    s.rect(x+w*.36,y+h*.5-6,w*.28,12,C["blue"],radius=2)
    s.circle(x+12,y+h*.5,9,C["ice"],C["teal"],1.8)
    s.circle(x+w*.65,y+h*.5+20,4,C["red"])
    label(s,x+8,y+h+14,w-16,"attoDRY",22,C["blue"],True,h=34,align="center")


def resistor(s,x,y,w=100,color=None):
    color=color or C["purple"]
    pts=[(x,y),(x+10,y)]
    for i in range(8):pts.append((x+15+i*9,y+(-7 if i%2==0 else 7)))
    pts.extend([(x+w-10,y),(x+w,y)])
    for a,b in zip(pts,pts[1:]):s.line(*a,*b,color,2)


def optical_disc(s,x,y,r=27):
    s.circle(x,y,r,C["ice"],C["teal"],1.5)
    for dy in (-16,0,16):s.line(x-16,y+dy,x+16,y+dy,C["teal"],4)
    s.circle(x,y,4,C["white"],C["teal"])


def optical_plate(s,x,y,label_text,angle=0):
    s.rect(x-10,y-28,20,56,C["ice"],C["teal"],radius=3,lw=1.5)
    s.line(x-7,y+20,x+7,y-20,C["teal"],2)
    label(s,x-57,y+36,114,label_text,15,C["teal"],True,align="center")


def table(s,x,y,width,columns,rows,colfracs,rowh=42,fontsize=18):
    s.rect(x,y,width,rowh*(len(rows)+1),C["white"],C["line"],radius=10)
    xx=[x]
    for frac in colfracs[:-1]:xx.append(xx[-1]+frac*width)
    for i,txt in enumerate(columns):
        label(s,xx[i]+12,y+10,colfracs[i]*width-24,txt,fontsize,C["teal"],True,h=rowh-8)
    for r,row in enumerate(rows):
        yy=y+rowh*(r+1)
        if r%2==0:s.rect(x+1,yy,width-2,rowh,C["bg"])
        for i,txt in enumerate(row):
            label(s,xx[i]+12,yy+9,colfracs[i]*width-24,txt,fontsize,C["ink"],h=rowh-6)


def footer(s,n,total):
    color="B1C2DA" if s.dark else C["muted"]
    s.line(54,687,1226,687,"31435B" if s.dark else C["line"],1)
    label(s,55,695,1100,s.source or "LabOS  |  Cross-PC nonlinear Hall and BVPE measurement workflows",11,color,h=19)
    label(s,1168,693,58,f"{n:02d}/{total:02d}",12,color,h=21,align="right")


def build():
    s=new("LABOS","LabOS",dark=True,note="This presentation explains LabOS through a concrete two-PC instrument scenario. It is a capability and architecture presentation, not a report of measured sample results. The central idea is to organize optical excitation, cryogenic environment, electrical transport and photovoltage or photocurrent readout into reproducible stages with shared evidence.")
    s.pill(63,44,251,"DISTRIBUTED EXPERIMENTS","BBA5FF","263453",14)
    s.text(63,119,1140,115,"LabOS",81,C["white"],True)
    s.text(67,251,1120,122,"One experiment. Multiple PCs.\nA connected measurement system.",43,C["white"],True)
    label(s,67,393,1100,"Nonlinear Hall transport + bulk photovoltaic response",28,"BDCEE4",h=49)
    for x,w,t,body in [(67,330,"PC A: optical resources","SuperK + infrared spectroscopy"),(477,330,"Central scientific agent","Planning + orchestration + evidence"),(887,330,"PC B: sample and readout","attoDRY + electrical / optical control")]:
        s.node(x,503,w,100,t,body,C["teal"] if x!=477 else C["purple"],C["ice"] if x!=477 else C["plum"],22)
    s.arrow([(397,553),(477,553)],"5FC9D5",3)
    s.arrow([(807,553),(887,553)],"5FC9D5",3)
    label(s,67,642,1120,"A system-level view of hardware, references, timing, data and scientific decisions",19,"BDCEE4",h=30)

    s=new("01 / SCIENTIFIC SCENARIO","Two response channels, one experimental context",
          "Electrical and optical excitation share the same sample coordinates: T, B and gate voltage Vg.",
          note="The electrical branch tests transverse second-order response under AC current drive. The optical branch measures chopped-light photocurrent or photovoltage while changing power, polarization and excitation spectrum. Both share sample identity, wiring configuration and environmental readbacks. A common context enables comparisons without assuming a common microscopic mechanism.")
    s.box(54,205,565,286,"Nonlinear Hall transport","Drive: lock-in sine output + series resistor\nReadout: longitudinal Vxx and transverse Vxy\nAxes: current, frequency, T, B and Vg\nControls: harmonics, return points, repeatability",C["purple"],size=22,title_size=26)
    s.box(647,205,579,286,"BVPE / photocurrent response","Drive: SuperK or a 730 nm laser\nReference: optical chopper at fchop\nAxes: optical power, polarization, spectrum, T/B/Vg\nControls: dark, power reference and repeat scans",C["teal"],size=22,title_size=26)
    for x,text in [(76,"Shared sample"),(366,"Readback coordinates"),(656,"Controlled stages"),(946,"Linked evidence")]:s.pill(x,538,256,text,size=19)
    s.band("The research task defines the sequence; device ownership defines where each action executes.",size=23)

    s=new("02 / FIGURE 1 — SYSTEM ARCHITECTURE","An evidence-driven hierarchy across two control PCs",
          "Scientific reasoning, deterministic orchestration and local instrument ownership are separate layers.",
          source="Architecture presentation inspired by QUANTA Fig. 1 [1]; original LabOS redraw for this instrument scenario.",
          note="The operator supplies a scientific objective, sample constraints and physical interventions. A central scientific agent combines planning, analysis and troubleshooting with a versioned evidence store. Proposed stages pass through deterministic schema, units, limits, resource-lock and command-ledger checks. Persistent workers on PC A and PC B own device sessions, execute bounded actions and retain local evidence. Commands flow down; measurements, observed states and faults flow back up. The small device panels identify resources; later figures expand their actual signal paths.")
    s.arrow([(299,234),(331,234)],C["amber"],2.3)
    s.arrow([(911,236),(880,236)],C["purple"],2.3)
    s.arrow([(606,293),(606,318)],C["purple"],2.5)
    s.arrow([(760,318),(760,293)],C["green"],2.5)
    s.arrow([(1068,318),(1068,293)],C["green"],2.2)
    region(s,55,188,244,105,"Researcher",C["amber"],C["sand"])
    label(s,69,228,215,"Question, sample, limits\nand physical interventions",16,h=54)
    region(s,331,188,549,105,"Central scientific agent",C["purple"],C["plum"])
    for x,t in [(344,"Planning"),(519,"Analysis"),(694,"Troubleshooting")]:s.node(x,244,166,35,t,color=C["purple"],size=16)
    region(s,911,188,314,105,"Evidence and memory",C["green"],C["mint"])
    label(s,925,228,283,"Papers / manuals / protocols\nCode versions / previous runs",16,h=54)
    region(s,55,318,1170,96,"Deterministic execution coordinator",C["teal"],C["ice"])
    for x,t in [(73,"Schema + units"),(300,"Limits + locks"),(527,"Stage state"),(754,"Command ledger"),(981,"QC + hashes")]:
        s.node(x,365,207,35,t,color=C["teal"],size=16)
    for x in (206,760):s.arrow([(x,414),(x,435)],C["purple"],2.5,head=7)
    for x in (388,1063):s.arrow([(x,435),(x,414)],C["green"],2.5,head=7)
    region(s,55,435,455,203,"PC A agent: optical worker",C["teal"])
    label(s,70,475,421,"Persistent sessions / drivers / local watchdog",16,h=25)
    instrument(s,72,508,200,91,"SuperK","Source + band control",("CMD","STATE"))
    instrument(s,293,508,200,91,"IR spectrometer","Reference spectrum",("TRIG","DATA"))
    label(s,73,620,416,"Command journal + local raw-data outbox",15,C["green"],True,h=22)
    region(s,540,435,685,203,"PC B agent: environment, transport and optics",C["teal"])
    label(s,556,475,654,"Persistent sessions / drivers / local watchdog / artifact cache",16,h=25)
    for x,t,body in [(558,"attoDRY","T / B state"),(725,"Transport x2","Vxx / Vxy"),(892,"Optical chain","PD / laser"),(1059,"Gate + pol.","2400 / motor")]:
        instrument(s,x,508,149,91,t,body,("I/O",))
    label(s,558,620,642,"BVPE lock-in + CLD1000 + power / polarization configuration",15,C["green"],True,h=22)
    label(s,70,651,1140,"DOWN: approved commands     UP: data, readbacks and faults     LOCAL: session ownership and recovery state",15,C["muted"],h=23)

    s=new("03 / LOCAL WORKER ARCHITECTURE","A PC agent is a persistent instrument service",
          "The central server schedules stages; the worker owns sessions, verifies actions and protects local evidence.",
          note="A local worker is more than a remote shell. It keeps instrument connections, translates finite capability calls through adapters, manages one owner per device and records each command identity. Status monitoring and the watchdog run independently of a long scientific conversation. Raw measurements are written locally before an artifact outbox synchronizes them with checksums. An ambiguous dispatched action is reconciled, not blindly replayed.")
    region(s,54,200,1172,366,"INSIDE EACH WINDOWS PC",C["teal"],C["ice"])
    s.node(79,262,240,90,"Network client","Outbound poll / heartbeat",C["purple"],size=22)
    s.node(365,262,243,90,"Persistent worker","Device ownership / dispatch",size=22)
    s.node(654,262,245,90,"Driver adapters","Finite device capabilities",size=22)
    s.node(944,262,256,90,"Instrument sessions","Vendor I/O and state",size=22)
    for a,b in [(319,365),(608,654),(899,944)]:s.arrow([(a,307),(b,307)],lw=2.3)
    s.node(79,417,240,91,"Command journal","IDs / outcomes / recovery",C["blue"],C["pale"],22)
    s.node(365,417,243,91,"Local watchdog","Contact loss / stop latches",C["amber"],C["sand"],22)
    s.node(654,417,245,91,"Raw-data cache","Atomic local artifact writes",C["green"],C["mint"],22)
    s.node(944,417,256,91,"Artifact outbox","Checksum / retry / acknowledge",C["green"],C["mint"],22)
    for x in (198,486,777,1072):s.arrow([(x,352),(x,417)],C["muted"],1.5,True)
    s.arrow([(654,462),(608,462)],C["amber"],1.5)
    s.band("A network interruption does not erase a command, transfer ownership or discard a saved measurement.",size=22)

    s=new("04 / RESOURCE MAP","The complete two-PC instrument inventory",
          "Device ownership stays local; instrument capabilities can participate in a shared multi-PC experiment.",
          note="This inventory follows the supplied apparatus. PC A owns SuperK and the IR spectrometer. PC B owns attoDRY, two electrical transport lock-ins, a separate BVPE lock-in, a chopper, a power-monitoring photodiode, a 2400 gate source, the 730 nm laser and CLD1000 current controller, and a motorized polarization element. The electrical drive is a function of one transport lock-in, not a fourth lock-in.")
    table(s,54,194,1172,["Owner","Instrument / resource","Experiment role"],[
        ("PC A","SuperK supercontinuum source","Optical source and excitation-band configuration"),
        ("PC A","Infrared spectrometer","Incident / reference spectrum and optical diagnostics"),
        ("PC B","attoDRY","Temperature, magnetic field and sample-state readbacks"),
        ("PC B","Transport lock-in x2","Master drive + Vxx; Vxy with selected harmonic"),
        ("PC B","Chopper + BVPE lock-in","Optical modulation and referenced photoresponse"),
        ("PC B","Photodiode (PD)","Optical-power monitoring and sample-plane calibration"),
        ("PC B","2400 source-measure unit","Gate voltage Vg and gate leakage Ig"),
        ("PC B","730 nm laser + CLD1000","Laser excitation and drive-current control"),
        ("PC B","Motorized polarizer / quarter-wave plate","Linear-polarization angle / polarization state")],
        [.10,.37,.53],rowh=40,fontsize=17)
    s.band("Two transport lock-ins + one BVPE lock-in; one configured source path and one shared sample context.",size=21)

    s=new("05 / FIGURE 2 — EXPERIMENT TOPOLOGY","One sample connects the optical and electrical chains",
          "Control ownership follows PCs; light, voltage, current and physical references follow the apparatus.",
          note="The sample can receive light from PC A's SuperK or PC B's 730 nm source. A configured reference branch feeds the IR spectrometer; a power-monitoring branch supports sample-plane power calibration. PC B provides temperature, magnetic field, gate bias, electrical excitation and both transport and optical lock-in readout. Optical and electrical acquisitions are staged according to the selected wiring configuration. The cryostat drawing is an optical-access schematic, not a vendor CAD model.")
    region(s,54,188,300,192,"PC A: source + spectrum",C["teal"],C["ice"])
    instrument(s,71,231,265,91,"SuperK","Excitation band / spectrum")
    s.node(71,341,265,30,"IR reference spectrum",color=C["teal"],size=16)
    region(s,54,407,300,186,"PC B: laser excitation",C["purple"],C["plum"])
    instrument(s,71,450,265,88,"730 nm laser","CLD1000 current control")
    label(s,76,561,256,"Drive setting -> calibrated P",15,C["purple"],h=25)
    s.arrow([(336,276),(387,276),(387,356),(432,356)],C["teal"],3)
    s.arrow([(336,494),(387,494),(387,356)],C["teal"],3)
    s.arrow([(387,350),(336,350)],C["teal"],1.7,True)
    optical_disc(s,457,356,26)
    optical_plate(s,559,356,"Polarizer / QWP")
    s.arrow([(483,356),(549,356)],C["teal"],3)
    s.arrow([(570,356),(655,356)],C["teal"],3)
    label(s,404,293,124,"Chopper",17,C["teal"],True,h=27,align="center")
    s.poly([(620,345),(631,356),(620,367),(609,356)],C["mint"],C["green"],1.3)
    s.arrow([(620,367),(620,489),(562,489)],C["green"],2)
    s.node(404,451,158,73,"PD monitor","Power calibration",C["green"],C["mint"],19)
    cryostat(s,655,230,190,250)
    s.arrow([(845,320),(894,320),(894,263),(960,263)],C["blue"],2)
    s.arrow([(845,350),(912,350),(912,363),(960,363)],C["blue"],2)
    s.arrow([(845,380),(890,380),(890,472),(960,472)],C["teal"],2)
    s.node(960,229,266,71,"Transport master","Drive fI + Vxx(1f)",C["blue"],C["pale"],21)
    s.node(960,329,266,71,"Transport follower","REF fI -> Vxy(2f)",C["blue"],C["pale"],21)
    s.node(960,436,266,75,"BVPE lock-in","REF fchop -> photoresponse",C["teal"],C["ice"],21)
    s.arrow([(1093,300),(1093,329)],C["amber"],2,True)
    s.arrow([(457,383),(457,418),(635,418),(635,606),(1093,606),(1093,511)],C["amber"],2,True)
    label(s,923,553,158,"Chopper REF\nfchop",16,C["amber"],True,h=49)
    s.node(655,548,190,47,"2400: Vg / Ig",color=C["purple"],size=19)
    s.arrow([(750,548),(865,548),(865,448),(845,448)],C["purple"],2)
    s.band("Legend: teal = optical / photoresponse; blue = transport readout; amber dashed = physical reference.",size=20)

    s=new("06 / CONTROL PLANE","Orchestration travels over HTTP(S), not signal cables",
          "Windows agents initiate outbound connections; device commands are durable, scoped and attributable.",
          note="PCs poll the central endpoint, return status through heartbeats and synchronize measurement artifacts. Central-to-PC arrows describe command payloads returned to these clients, not a requirement for inbound SSH access. An instrument resource is reserved for a run before dispatch. Command identity, boot session and ownership protect against accidental duplication or stale sessions. Local raw data are acknowledged separately from the command outcome.")
    s.node(451,193,378,99,"Central coordinator","Registry / reservation / stage ledger",C["purple"],C["plum"],26)
    for xx,title in [(55,"PC A agent"),(860,"PC B agent")]:
        s.node(xx,408,365,124,title,"Poll + heartbeat + artifact outbox",C["teal"],C["white"],27)
    s.arrow([(451,227),(240,227),(240,408)],C["purple"],2.6)
    s.arrow([(829,227),(1038,227),(1038,408)],C["purple"],2.6)
    s.arrow([(420,470),(549,470),(549,292)],C["green"],2.6)
    s.arrow([(860,470),(731,470),(731,292)],C["green"],2.6)
    label(s,70,301,331,"APPROVED COMMAND\ncommand_id / device / stage\noperation / parameters / deadline",19,C["purple"],h=90)
    label(s,872,301,342,"OBSERVED EVIDENCE\nreadbacks / timestamps / flags\nartifact_id / checksum / outcome",19,C["green"],h=90)
    s.node(494,525,292,54,"Shared experiment identity",color=C["blue"],fill=C["pale"],size=20)
    s.band("No SSH dependency: the network coordinates state; physical references establish lock-in phase.",size=23)

    s=new("07 / FIGURE 3 — TIMING AND SYNCHRONIZATION","A point barrier links conditions before acquisition",
          "A shared point_id provides correspondence; acquisition intervals and physical references provide timing context.",
          note="At each experimental point, optical preparation on PC A and environmental preparation on PC B can proceed independently. Each worker reports the requested point identity, actual readback and readiness evidence. The coordinator releases acquisition only after the required participants are ready. Each trace records its own start and end time. The electrical reference fI and optical chopper reference fchop remain physical signals, independent of network latency. Hardware triggering can be added where the experiment requires strict simultaneous sampling.")
    for i,name in enumerate(["Coordinator","PC A","PC B","Electrical ref.","Optical ref."]):
        yy=214+i*77
        label(s,54,yy+11,153,name,19,C["purple"] if i==0 else C["amber"] if i>2 else C["teal"],True,h=31)
        s.line(217,yy+26,1210,yy+26,C["line"],1.4)
    for x,w,t in [(224,187,"Issue point_id"),(501,203,"Join READY states"),(799,216,"Release acquisition"),(1070,140,"QC + archive")]:s.node(x,214,w,51,t,color=C["purple"],fill=C["plum"],size=17)
    for yy,first,last in [(291,"Set source / band / optics","Reference spectrum"),(368,"Set T / B / Vg; settle","Lock-ins + PD")]:
        s.node(253,yy,247,51,first,size=16)
        s.node(542,yy,161,51,"Readback + READY",size=16)
        s.node(799,yy,294,51,last,size=18)
    s.line(749,192,749,431,C["purple"],2,True)
    label(s,705,435,106,"Barrier",16,C["purple"],True,h=25,align="center")
    s.arrow([(236,471),(1208,471)],C["amber"],2.4)
    s.arrow([(236,548),(1208,548)],C["amber"],2.4)
    label(s,276,483,900,"fI: master oscillator -> follower REF; select harmonic n",18,C["amber"],h=29)
    label(s,276,560,900,"fchop: chopper controller -> BVPE lock-in REF",18,C["amber"],h=29)
    s.band("Store conditions AND time windows. Shared coordination is not a claim of zero-skew sampling.",size=22)

    s=new("08 / PREPARATION MANIFEST","Translate the apparatus into a reproducible run setup",
          "Reusable device capabilities are combined with sample-specific wiring, calibration and experimental limits.",
          note="The setup manifest describes physical ownership, instrument interfaces, wiring and the calibration conventions relevant to a campaign. It distinguishes a device limit from a sample-specific authorized envelope and from settings already supported by prior data. The user can reuse the device setup while changing the objective, scan coordinates, reference tests or closure policy for a new experiment.")
    table(s,54,195,1172,["Record","Configuration content","Used by"],[
        ("Device ownership","PC A/B, resource IDs, connection and driver versions","Dispatch + locks"),
        ("Sample and wiring","Sample ID, contacts, Vxx/Vxy mapping, gate, optical path","All stages"),
        ("Electrical convention","Rs calibration, actual I, RMS/peak, fI, harmonics, phase","Hall analysis"),
        ("Optical convention","Source, excitation spectrum, PD calibration, polarization zero","BVPE analysis"),
        ("Environment","T/B/Vg targets, readbacks and settling criteria","Point barrier"),
        ("Action envelope","Approved drive, optical power, gate leakage and rates","Validation + QC"),
        ("End-state policy","Excitation off; gate and environment follow defined policy","Run closure")],
        [.19,.61,.20],rowh=49,fontsize=17)
    s.band("A setup is both a resource map and an explicit statement of what each measurement means.",size=23)

    s=new("09 / FIGURE 4 — NONLINEAR HALL CIRCUIT","Two transport lock-ins, with explicit drive and sense paths",
          "The master lock-in supplies AC excitation and Vxx(1f); the follower measures Vxy at a selected harmonic.",
          source="Circuit-level scenario based on the supplied apparatus; harmonic measurement rationale: [2,3].",
          note="The master transport lock-in both generates the sine wave and reads longitudinal voltage using its internal reference. Its oscillator reference is routed physically to the follower, which selects harmonic two for a transverse second-order measurement. The sample current is calibrated from the series-resistor voltage with an explicit RMS convention. The drive return is drawn separately from voltage sense leads. The transverse and longitudinal inputs may share a sample contact according to the selected differential wiring. The 2400 provides an independent gate voltage with leakage monitoring.")
    region(s,55,202,270,285,"MASTER LOCK-IN",C["purple"],C["plum"])
    label(s,72,246,234,"Internal oscillator: fI",19,C["purple"],h=31)
    for yy,t in [(318,"Vxx HI"),(363,"Vxx LO"),(452,"Drive return")]:label(s,83,yy-13,218,t,17,C["purple"],h=26)
    label(s,83,283,218,"Sine OUT",17,C["purple"],True,h=27)
    for yy in (291,318,363,452):s.circle(325,yy,4,C["purple"])
    # Six-terminal Hall bar with a gated channel.
    s.rect(541,333,254,54,C["pale"],C["blue"],radius=7,lw=1.8)
    for xx in (600,718):
        s.line(xx,302,xx,333,C["blue"],5)
        s.line(xx,387,xx,416,C["blue"],5)
        s.circle(xx,302,4,C["blue"]);s.circle(xx,416,4,C["blue"])
    s.circle(530,360,5,C["purple"]);s.circle(806,360,5,C["purple"])
    s.line(530,360,541,360,C["purple"],2);s.line(795,360,806,360,C["purple"],2)
    label(s,545,342,243,"SAMPLE",24,C["blue"],True,h=37,align="center")
    label(s,517,382,57,"I+",16,C["purple"],True,h=25)
    label(s,783,382,57,"I-",16,C["purple"],True,h=25)
    s.line(650,402,687,402,C["purple"],5)
    s.line(668,402,668,519,C["purple"],1.8)
    s.arrow([(325,291),(399,291),(399,246),(420,246)],C["purple"],2.4)
    resistor(s,420,246,100)
    s.arrow([(520,246),(530,246),(530,360)],C["purple"],2.4)
    label(s,415,207,110,"Rs",23,C["purple"],True,h=33,align="center")
    label(s,565,225,294,"I_rms = V_Rs,rms / Rs",18,C["purple"],True,h=31)
    s.arrow([(806,360),(855,360),(855,499),(355,499),(355,452),(325,452)],C["purple"],2)
    s.arrow([(600,302),(454,302),(454,318),(325,318)],C["blue"],1.8)
    s.arrow([(718,302),(718,279),(475,279),(475,363),(325,363)],C["blue"],1.8)
    region(s,940,274,286,220,"FOLLOWER LOCK-IN",C["blue"],C["pale"])
    label(s,958,317,250,"Differential Vxy input\nExternal REF = fI\nHarmonic n = 2\nSave X, Y and lock status",19,C["blue"],h=115)
    s.circle(940,337,4,C["blue"]);s.circle(940,393,4,C["blue"])
    s.arrow([(718,302),(885,302),(885,337),(940,337)],C["blue"],1.8)
    s.arrow([(718,416),(908,416),(908,393),(940,393)],C["blue"],1.8)
    s.node(556,519,224,57,"2400: Vg + Ig",color=C["purple"],size=21)
    s.arrow([(190,487),(190,594),(1081,594),(1081,494)],C["amber"],2.3,True)
    label(s,256,551,295,"Physical oscillator REF: fI",16,C["amber"],True,h=25)
    label(s,761,600,457,"Crossings without dots are not connections.",13,C["muted"],h=18)
    s.band("Vxx / Vxy are spatial channels. X / Y are phase components returned by EACH lock-in.",size=23)

    s=new("10 / HARMONIC ACQUISITION MODES","Change acquisition mode, preserve channel meaning",
          "The same two transport instruments support a sequence of complementary harmonic and reference stages.",
          note="The first configuration reads Vxx at the fundamental and Vxy at the second harmonic. A subsequent baseline stage can select fundamental transverse voltage, and another stage can inspect longitudinal second-harmonic pickup. These are distinct acquisition stages for single-demodulator instruments; they are not presented as four simultaneous channels from two generic lock-ins. Every record includes the harmonic, phase reference, range and RMS convention.")
    table(s,54,199,1172,["Stage","Master: Vxx","Follower: Vxy","Scientific purpose"],[
        ("A: transport baseline","1f, internal REF","1f, external fI","Linear response and pickup baseline"),
        ("B: second-order test","1f, internal REF","2f, external fI","Vxy(2ω) versus actual Iω²"),
        ("C: harmonic control","2f, internal REF","2f, external fI","Longitudinal / transverse comparison"),
        ("D: return reference","Chosen reference mode","Same reference settings","Repeatability and drift check")],
        [.20,.23,.24,.33],rowh=65,fontsize=18)
    s.box(54,551,570,99,"Preserve the full readout","X / Y, frequency, harmonic, gain, range and flags",C["teal"],size=18,title_size=22)
    s.box(652,551,574,99,"Keep inference separate","Quadratic response is evidence, not a unique mechanism",C["purple"],size=18,title_size=22)

    s=new("11 / HALL CAMPAIGN LOGIC","Turn a nonlinear signal into a controlled comparison",
          "Outer coordinates: T × B × Vg. Inner tests: drive amplitude, frequency, harmonic and return references.",
          note="A campaign starts from a low-drive dark reference, then tests excitation-amplitude dependence and returns to a reference setting. Frequency and harmonic controls help separate a reproducible second-order response from thermal effects, contact nonlinearities and pickup. Field symmetry must be interpreted for the chosen physical model rather than imposed using a universal linear-Hall rule. The diagrams describe measurement logic, not measured sample curves.")
    g.timeline(s,54,207,[("Prepare state","T / B / Vg readbacks"),("Dark baseline","Low drive + 1f"),("Drive sweep","Actual Iω + 2f"),("Return controls","Repeat / f / harmonics"),("Evidence review","Qualify + compare")],step_h=112)
    s.box(54,371,568,222,"Configured measurements","Current bracket and return point\nFrequency / phase / harmonic controls\nEnvironmental and gate-leakage traces\nRepeated reference acquisitions",C["purple"],size=22,title_size=24)
    s.box(654,371,572,222,"Evidence for the next decision","Readable and referenced signals?\nConsistent response at reference settings?\nDrive scaling preserved across controls?\nWhich comparison resolves ambiguity?",C["teal"],size=22,title_size=24)
    s.band("The agent proposes the next discriminating measurement within the configured experimental envelope.",size=22)

    s=new("12 / FIGURE 5 — BVPE OPTICAL AND READOUT PATH","Optical drive, power and referenced readout",
          "The 730 nm and SuperK paths converge on the same configured polarization and sample environment.",
          source="Optical / photocurrent scenario for LabOS; BVPE experimental context: Osterhoudt et al. [4].",
          note="SuperK provides a configured spectral excitation state, while the 730 nm diode branch is controlled through CLD1000 drive current. A selected beam path passes through the chopper and polarization element to an optical-access sample mount. The reference spectrum and PD power monitor characterize the optical condition; a calibration transfer links the monitor to power at the sample plane. The BVPE lock-in measures photovoltage directly or photocurrent through its configured current input or current preamplifier. Its physical reference comes from the chopper, not from the network.")
    instrument(s,55,201,247,92,"SuperK","Band / source configuration",("SOURCE",))
    instrument(s,55,396,247,92,"730 nm laser","Selected laser excitation",("LIGHT",))
    s.node(55,535,247,57,"CLD1000: I_LD",color=C["purple"],fill=C["plum"],size=21)
    s.arrow([(178,535),(178,488)],C["purple"],2)
    s.arrow([(302,248),(350,248),(350,350),(390,350)],C["teal"],3)
    s.arrow([(302,442),(350,442),(350,350)],C["teal"],3)
    optical_disc(s,418,350,28)
    label(s,360,284,119,"Chopper",18,C["teal"],True,h=27,align="center")
    optical_plate(s,515,350,"Polarizer")
    optical_plate(s,620,350,"QWP / motor")
    s.arrow([(446,350),(505,350)],C["teal"],3)
    s.arrow([(525,350),(610,350)],C["teal"],3)
    s.arrow([(630,350),(737,350)],C["teal"],3)
    s.poly([(681,338),(693,350),(681,362),(669,350)],C["mint"],C["green"],1.4)
    cryostat(s,737,224,180,250)
    label(s,737,197,180,"Optical-access sample",16,C["blue"],True,h=26,align="center")
    s.arrow([(681,362),(681,499),(611,499)],C["green"],2)
    instrument(s,381,461,230,91,"PD power monitor","Responsivity / transfer K",("POWER",),C["green"])
    s.node(381,201,230,60,"IR reference spectrum",color=C["teal"],size=17)
    s.arrow([(350,294),(350,231),(381,231)],C["teal"],1.7,True)
    region(s,969,279,257,204,"BVPE LOCK-IN",C["blue"],C["pale"])
    label(s,985,325,225,"Photovoltage input\nor current-mode readout\nGain / range / X / Y\nExternal REF = fchop",18,C["blue"],h=112)
    s.arrow([(917,350),(943,350),(943,366),(969,366)],C["blue"],2.5)
    s.arrow([(418,378),(418,420),(700,420),(700,604),(1097,604),(1097,483)],C["amber"],2,True)
    label(s,939,545,147,"Chopper REF\nfchop",16,C["amber"],True,h=49)
    s.node(737,538,180,52,"2400: Vg / Ig",color=C["purple"],size=18)
    s.arrow([(827,538),(930,538),(930,414),(917,414)],C["purple"],2)
    s.band("fchop is the optical-intensity envelope reference; it is not the optical carrier frequency or Hall 2fI.",size=21)

    s=new("13 / CALIBRATION AND NORMALIZATION","Describe the optical state at the sample plane",
          "Drive settings, monitor readings and sample-plane power are related through an explicit calibration.",
          note="CLD1000 sets diode drive current; it does not by itself measure optical power at the sample. The PD reading is converted through detector response, monitor electronics and an optical transfer calibration. This calibration can depend on wavelength and the configured optical path, including window transmission and polarization elements. A photocurrent channel also needs its amplifier gain and the modulation-amplitude convention. These definitions are stored with each acquisition rather than inferred after the experiment.")
    g.timeline(s,54,211,[("Source setting","I_LD or band setting"),("PD readback","Detector + electronics"),("Calibration K","Wavelength / path"),("Sample-plane P","Window / polarization"),("Normalized signal","Current or voltage / P")],step_h=115)
    s.box(54,382,365,209,"Power definition","Monitor responsivity\nCalibration transfer K\nSample-plane reference\nModulation amplitude convention",C["green"],size=21,title_size=24)
    s.box(457,382,365,209,"Polarization definition","Polarizer angle zero\nQWP angle and retardance\nInput polarization state\nMotor position readback",C["teal"],size=21,title_size=24)
    s.box(860,382,366,209,"Electrical definition","Voltage or current readout\nTransimpedance gain, if used\nX / Y phase and lock status\nSource-drain bias convention",C["blue"],size=21,title_size=24)
    s.band("For current readout: Iph = Vread / G_TIA. Power normalization must state its calibration and units.",size=22)

    s=new("14 / BVPE CAMPAIGN LOGIC","Combine spectrum, power, polarization and environment",
          "PC A supplies optical resources; PC B supplies polarization, modulation, sample state and electrical readout.",
          note="A BVPE campaign includes dark and reference acquisitions, optical-power characterization, polarization scans and environmental sweeps. The 730 nm branch is useful for fixed-wavelength power and polarization measurements. The SuperK branch is configured as a selected excitation band or a measured broadband illumination state. The IR spectrometer operates within its configured response band; the power monitor and optical transfer calibration provide the power context. The current or voltage response can then be compared under common sample-state coordinates.")
    g.timeline(s,54,207,[("Dark / reference","Background + spectrum"),("Power calibration","Source -> PD -> P"),("Polarization scan","Linear angle / QWP"),("State sweep","T / B / Vg / spectrum"),("Return reference","Dark / P / repeat")],step_h=112)
    table(s,54,371,1172,["Branch","Configured scan","Associated evidence"],[
        ("730 nm excitation","Drive setting × power × polarization","PD, angle, gain and fchop readbacks"),
        ("SuperK excitation","Excitation band / recorded incident spectrum","Reference spectrum and power calibration"),
        ("Environmental sweep","T × B × Vg with selected optical state","Actual state, settling and gate leakage"),
        ("Reference return","Dark / reference power / repeated polarization","Background, stability and repeatability")],
        [.21,.39,.40],rowh=48,fontsize=17)
    s.band("A chopped-light signal is an observation; mechanism assignments require the matching control experiments.",size=21)

    s=new("15 / JOINT CAMPAIGN GRAPH","A shared coordinate links dark and illuminated stages",
          "campaign_id links the research objective; stage/run IDs preserve branches; point IDs link conditions.",
          note="A joint campaign can prepare an environmental state, acquire dark transport, characterize the optical condition, acquire BVPE and then repeat a dark or power reference. PC A and PC B participate only where their capabilities are needed. Source or wiring changes are explicit stage transitions and may include operator actions. The campaign graph keeps branches and return references distinct instead of flattening them into one undifferentiated curve.")
    s.node(54,202,227,77,"Prepare T / B / Vg","PC B: observed state",color=C["purple"],fill=C["plum"],size=20)
    s.node(358,202,240,77,"Dark Hall stage","PC B: drive + Vxx / Vxy",color=C["blue"],fill=C["pale"],size=20)
    s.node(674,202,240,77,"Optical reference","PC A + PC B: spectrum / PD",size=20)
    s.node(989,202,237,77,"BVPE stage","PC B: fchop + photoresponse",size=20)
    for a,b in [(281,358),(598,674),(914,989)]:s.arrow([(a,241),(b,241)],lw=2.5)
    s.arrow([(1107,279),(1107,363),(791,363),(791,409)],C["green"],2.4)
    s.node(674,409,240,81,"Return references","Dark / power / repeat",C["green"],C["mint"],21)
    s.node(358,409,240,81,"Evidence review","Quality + controls + comparison",C["purple"],C["plum"],21)
    s.arrow([(674,450),(598,450)],C["green"],2.4)
    s.arrow([(358,450),(168,450),(168,279)],C["purple"],2.3,True)
    label(s,55,477,270,"Next state / follow-up stage",16,C["purple"],True,h=27)
    s.rect(54,537,1172,61,C["white"],C["line"],radius=9)
    label(s,74,553,1132,"sample + wiring + observed T/B/Vg + source state + time windows + calibration versions",21,C["navy"],True,h=34,align="center")
    s.band("Compare linked conditions and controls before inferring relationships between electrical and optical responses.",size=21)

    s=new("16 / DATA AND PROVENANCE","A measurement is more than a scalar value",
          "Keep requested values, observed state, raw channels, calibration and quality decisions in separate fields.",
          note="A complete measurement record joins identity, requested setpoints and observed conditions without conflating them. The raw electrical and optical channels carry harmonic and reference definitions. Detector readings, spectrum and calibration identifiers explain the optical state. Quality assessment is separately versioned so that rejected data remain available for audit. Hashes link immutable plans, setup versions, artifacts and analysis products. The schema shown here is a capability-level record model rather than a claim that all fields share one instrument sampling clock.")
    s.box(54,196,352,381,"Identity and context","campaign / run / stage / point\nsample ID and wiring version\nplan + setup fingerprints\nrequested T / B / Vg\nobserved T / B / Vg / Ig\nacquisition start / end times\nsource + polarization configuration",C["purple"],size=20,title_size=23)
    s.box(443,196,352,381,"Raw measurement channels","Vxx: X, Y, n, fI\nVxy: X, Y, n, fI\nphotoresponse: X, Y, fchop\ninput mode / gain / range\nPD monitor and calibrated power\nreference spectrum S(λ)\nlocal file + artifact checksum",C["teal"],size=20,title_size=23)
    s.box(832,196,394,381,"Qualification and interpretation","reference lock / overload flags\nsettling / freshness evidence\naccepted / rejected / historical\ncalibration and analysis versions\nreference / return comparisons\nobservations vs. hypotheses\nclosure state and next decision",C["green"],size=20,title_size=23)
    s.band("Raw evidence is retained; derived analysis and interpretation remain attributable and revisable.",size=23)

    s=new("17 / EXECUTION STATE AND QUALITY","Explicit state transitions govern the next action",
          "A completed command, a synchronized artifact and a scientifically usable reading are distinct outcomes.",
          note="The coordinator moves a point through preparation, readiness, acquisition, synchronization and qualification. Rejected evidence is retained and can motivate a diagnostic plan. Unknown dispatch outcomes require ownership and state reconciliation instead of replay. Safe closure records observed output states; stopping electrical or optical excitation does not implicitly ramp a magnet or gate to zero. Physical rewiring or sample changes are explicit operator steps.")
    g.timeline(s,54,203,[("PREPARE","Set and read back"),("READY","Participants + criteria"),("ACQUIRE","Local raw-data write"),("SYNCHRONIZE","Artifact + checksum"),("QUALIFY","Flags + evidence")],step_h=100)
    s.node(865,377,340,77,"ACCEPT -> analyze","Preserve raw + calibration + context",C["green"],C["mint"],21)
    s.node(458,377,340,77,"REJECT -> diagnose","Keep raw / flags; stop affected excitation",C["red"],C["rose"],21)
    s.node(54,377,340,77,"UNKNOWN -> reconcile","Verify owner / command / physical state",C["amber"],C["sand"],21)
    s.arrow([(1110,303),(1110,377)],C["green"],2)
    s.arrow([(1110,330),(629,330),(629,377)],C["red"],2)
    s.arrow([(518,253),(518,345),(223,345),(223,377)],C["amber"],2,True)
    s.box(54,510,1172,90,"Closure is a recorded state, not just an acknowledgement","Excitation off and readback verified; gate / T / B follow the selected end-state policy.",C["teal"],size=20,title_size=23)
    s.band("The next proposed stage is validated again and respects operator gates and the configured action envelope.",size=21)

    s=new("18 / USER WORKFLOW","Start from the research objective, not a remote desktop",
          "Device configuration is reusable; each experiment supplies a sample, variables, controls and operating bounds.",
          note="The operator can describe a scientific task in natural language and review the resulting stages before execution. The example asks for dark nonlinear Hall and polarization-dependent BVPE at matched environmental coordinates. The PC-side configuration identifies resources, connections, drivers, data paths and local policies. The experiment-side configuration identifies the sample, scientific question, wiring, coordinate sequence and controls. The interface provides live state, data-quality feedback and an attributable run review.")
    s.rect(54,198,1172,107,C["plum"],radius=12)
    s.text(77,217,1126,77,'"Map dark nonlinear Hall versus T, B and Vg; then measure 730 nm power and polarization dependence at matching states, with return references."',25,C["purple"],True)
    g.timeline(s,54,354,[("Describe objective","Sample + question"),("Prepare setup","Resources + wiring"),("Review stages","Axes + controls"),("Execute together","State + data + faults"),("Review evidence","Findings + next step")],step_h=121)
    label(s,74,526,1130,"PC side: identity / instrument connections / drivers / local data / local stop policy\nExperiment side: sample / wiring / allowed ranges / coordinate order / references / closure",22,h=72)
    s.band("The scientist focuses on design and interpretation; LabOS organizes execution and evidence.",size=23)

    s=new("19 / REUSE AND SCALE","Reuse local code. Compose shared capabilities.",
          "An instrument capability is portable at the planning layer even when its vendor environment remains local.",
          note="Existing test scripts are valuable starting points for finite capability adapters: connect, read status, set, settle, acquire, save and stop with verification. Drivers keep manufacturer dependencies and physical connections local. The central resource graph can include more PCs while preserving resource locks, shared physical paths and local ownership. Code and protocols also become versioned evidence for planning, which is different from executing arbitrary retrieved code.")
    s.box(54,200,360,240,"Existing instrument code","Connect / identify / status\nSet / read back / settle\nAcquire / write raw data\nStop / verify output state",C["purple"],size=23,title_size=24)
    s.box(460,200,360,240,"Bounded local capability","Typed inputs and units\nDefined return data and flags\nTimeout / cancellation behavior\nExclusive device session",C["teal"],size=23,title_size=24)
    s.box(866,200,360,240,"Reusable scientific stage","Environment preparation\nHall harmonic acquisition\nOptical calibration / BVPE\nReference and diagnostic tests",C["blue"],size=23,title_size=24)
    s.arrow([(414,320),(460,320)],lw=2.5)
    s.arrow([(820,320),(866,320)],lw=2.5)
    s.node(456,492,370,65,"Central resource / capability graph",color=C["purple"],fill=C["plum"],size=20)
    for xx,t in [(64,"PC A: optics"),(356,"PC B: transport"),(648,"PC C: imaging"),(940,"PC N: new resources")]:
        s.node(xx,574,275,34,t,color=C["teal"],size=16)
        s.line(640,557,640,565,C["teal"],1.5)
        s.line(201,565,1077,565,C["teal"],1.5)
        s.arrow([(xx+137,565),(xx+137,574)],C["teal"],1.5,head=5)
    s.band("Scale by adding owned resources and verified capabilities, not by moving every instrument to one PC.",size=22)

    s=new("LABOS / TAKEAWAY","Connected instruments. Attributable science.",dark=True,
          note="LabOS connects a distributed set of laboratory resources around a scientific objective. In this scenario, it joins two PCs, two excitation paths, environmental and gate control, harmonic transport, and chopped-light readout. Deterministic execution and local ownership support dependable operation, while shared identities, calibrations, timestamps and quality records support scientific interpretation. The central agent can then propose the next useful comparison from the evidence.")
    s.pill(63,44,231,"LABOS CAPABILITY MAP","BBA5FF","263453",14)
    s.text(65,131,1140,133,"One coordinated experiment.\nMultiple instruments and PCs.",46,C["white"],True)
    for i,(title,body) in enumerate([("Coordinate","Optical sources, sample state, transport and modulation"),("Preserve meaning","References, harmonics, power calibration and timestamps"),("Close the loop","Qualified observations, controls and a justified next stage")]):
        yy=350+i*88
        s.circle(78,yy+15,8,"5FC9D5")
        label(s,106,yy,307,title,28,"71D8DF",True,h=42)
        label(s,445,yy+3,759,body,23,"BDCEE4",h=43)
    label(s,65,642,1136,"Nonlinear Hall + BVPE: a concrete example of composable, evidence-driven experimentation",20,"BDCEE4",h=31)

    s=new("APPENDIX / REFERENCES","Scientific context and diagram provenance",
          "All architecture, apparatus, circuit, timing and state diagrams are original LabOS scenario drawings.",
          note="The instrument inventory and drive method were supplied and confirmed by the user. QUANTA is the framework reference for separating scientific reasoning, deterministic execution and persistent hardware ownership. The nonlinear Hall papers motivate fundamental and second-harmonic readout and the need for controls. The BVPE paper provides optical-response context. These sources are not used as measured data from this apparatus. The cryostat and front-panel illustrations are conceptual, with roles and interfaces expressed through experiment configuration.")
    refs=[("[1] Scientific-agent architecture","Rha et al., Autonomous Quantum Measurement with Agentic AI (2026).","https://arxiv.org/abs/2610.38850"),
          ("[2] Nonlinear Hall theory","Sodemann and Fu, Physical Review Letters 115, 216806 (2015).","https://doi.org/10.1103/PhysRevLett.115.216806"),
          ("[3] Nonlinear Hall measurement","Ma et al., Nature 565, 337-342 (2019).","https://doi.org/10.1038/s41586-018-0807-6"),
          ("[4] Bulk photovoltaic response","Osterhoudt et al., Nature Materials 18, 471-475 (2019).","https://doi.org/10.1038/s41563-019-0297-4")]
    for i,(t,b,u) in enumerate(refs):
        y=192+i*96
        label(s,65,y,1138,t,21,C["teal"],True,h=31)
        label(s,65,y+32,1138,b,20,h=30)
        label(s,65,y+61,1138,u,17,C["blue"],h=27)
    s.band("Apparatus and interfaces: the supplied two-PC configuration. Figures explain system capabilities and workflows.",size=20)


def main():
    build()
    for n,s in enumerate(g.SLIDES,1):footer(s,n,len(g.SLIDES))
    errors=[f"slide {i}: {e}" for i,s in enumerate(g.SLIDES,1) for e in s.errors]
    if errors:raise ValueError("\n".join(errors))
    title="LabOS: Cross-PC Nonlinear Hall and BVPE Measurement System"
    ppt=g.render_pptx("LabOS_Technical_Overview_EN.pptx",title,"System architecture, apparatus, timing and measurement workflows",notes_source_label="Reference: ")
    pdf=g.render_pdf("LabOS_Technical_Overview_EN.pdf",title)
    scenes=[dict(title=s.title,section=s.section,ops=s.ops,note=s.note,source=s.source) for s in g.SLIDES]
    (OUT/"slides_scene_EN.json").write_text(json.dumps(scenes,indent=2,ensure_ascii=False))
    notes="# LabOS technical presentation — speaker notes\n\n22 slides. Suggested talk length: 20–25 minutes.\n\n"
    for i,s in enumerate(g.SLIDES,1):
        notes+=f"## {i:02d} | {s.title}\n\n{s.note}\n\n"
        if s.source:notes+=f"Reference: {s.source}\n\n"
    (OUT/"Speaker_Notes_EN.md").write_text(notes.rstrip()+"\n",encoding="utf-8")
    print(json.dumps(dict(slides=len(g.SLIDES),pptx=str(ppt),pdf=str(pdf),geometry="PASS")))


if __name__=="__main__":main()
