#!/usr/bin/env python3
"""Regenerate images/architecture.svg for the current spectHR codebase."""
from pathlib import Path

OUT = Path(__file__).parent.parent / "images" / "architecture.svg"
W, H = 1440, 1720

# ── tiny SVG helpers ──────────────────────────────────────────────────────────
def e(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def lane(x,y,w,h,c):  return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" class="layer-{c}" rx="6"/>'
def box(x,y,w,h,c,rx=5): return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" class="box-{c}" rx="{rx}"/>'
def tc(x,y,s,c='label'): return f'<text x="{x}" y="{y}" text-anchor="middle" class="{c}">{e(s)}</text>'
def tl(x,y,s,c='label'): return f'<text x="{x}" y="{y}" text-anchor="start"  class="{c}">{e(s)}</text>'
def tr(x,y,s,c='label'): return f'<text x="{x}" y="{y}" text-anchor="end"    class="{c}">{e(s)}</text>'

def arr(x1,y1,x2,y2,lbl=None):
    p=[f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="arrow" marker-end="url(#arrow)"/>']
    if lbl:
        p.append(tc((x1+x2)//2+3,(y1+y2)//2-3,lbl,'arr-label'))
    return '\n'.join(p)

def harr(x1,x2,y): return arr(x1,y,x2,y)
def varr(x,y1,y2): return arr(x,y1,x,y2)

# ── build ─────────────────────────────────────────────────────────────────────
def build():
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"',
        '     font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif">',
        '''  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#374151"/>
    </marker>
    <style>
      .layer-ui  { fill: #eff6ff; }
      .layer-cfg { fill: #fffbeb; }
      .layer-fil { fill: #f8fafc; }
      .layer-ds  { fill: #f0fdf4; }
      .layer-ana { fill: #fdf2f8; }
      .layer-exp { fill: #f0fdfa; }
      .box-ui  { fill: #dbeafe; stroke: #1e40af; stroke-width: 1.5; }
      .box-cfg { fill: #fef3c7; stroke: #b45309; stroke-width: 1.5; }
      .box-fil { fill: #e2e8f0; stroke: #475569; stroke-width: 1.5; }
      .box-ds  { fill: #dcfce7; stroke: #15803d; stroke-width: 1.5; }
      .box-ana { fill: #fce7f3; stroke: #be185d; stroke-width: 1.5; }
      .box-exp { fill: #ccfbf1; stroke: #0d9488; stroke-width: 1.5; }
      .arrow   { stroke: #374151; stroke-width: 1.5; fill: none; }
      .title      { font-size: 21px; font-weight: 700; fill: #111827; }
      .subtitle   { font-size: 12px; fill: #6b7280; }
      .lane-label { font-size: 14px; font-weight: 700; }
      .ui-label  { fill: #1e3a8a; }
      .cfg-label { fill: #92400e; }
      .fil-label { fill: #334155; }
      .ds-label  { fill: #14532d; }
      .ana-label { fill: #9d174d; }
      .exp-label { fill: #065f46; }
      .label      { font-size: 12px; fill: #111827; }
      .label-bold { font-size: 12px; fill: #111827; font-weight: 700; }
      .sub        { font-size: 11px; fill: #4b5563; }
      .code       { font-family: ui-monospace,"SF Mono",Menlo,Consolas,monospace; font-size: 11px; fill: #111827; }
      .arr-label  { font-size: 10px; fill: #374151; font-style: italic; }
      .small      { font-size: 10px; fill: #6b7280; }
    </style>
  </defs>''',
        # header
        tc(W//2, 34, 'spectHR  architecture', 'title'),
        tc(W//2, 54, 'spectUI is the only reader of configuration · spectHR is pure compute · arrows show data / config flow', 'subtitle'),
    ]

    # ── LANE 1  Workspace I/O  (y=68, h=155) ────────────────────────────────
    L1y, L1h = 68, 155
    p += ['', f'  <!-- LANE 1 -->',
          lane(20,L1y,1400,L1h,'ui'),
          tl(36,L1y+20,'spectUI · Workspace I/O','lane-label ui-label')]

    Ay,Ah,Aw = L1y+32, 64, 210
    p += [box(40,Ay,Aw,Ah,'ui'),
          tc(40+Aw//2,Ay+22,'DefaultWorkSpace.json','label-bold'),
          tc(40+Aw//2,Ay+42,'on disk · user-editable','sub')]

    Bx,By,Bh,Bw = 268,L1y+32,64,170
    p += [box(Bx,By,Bw,Bh,'ui'),
          tc(Bx+Bw//2,By+22,'LoadWorkspace','label-bold'),
          tc(Bx+Bw//2,By+42,'workSpace.py','sub')]

    Cx,Cy,Cw,Ch = 456,L1y+29,432,98
    p += [box(Cx,Cy,Cw,Ch,'ui'),
          tc(Cx+Cw//2,Cy+18,'workspace · dict','label-bold'),
          tc(Cx+Cw//2,Cy+34,'FrequencyAnalysis · Profiles · TransferAnalysis','code'),
          tc(Cx+Cw//2,Cy+50,'RespirationAnalysis · CardioParameters · Calibration','code'),
          tc(Cx+Cw//2,Cy+66,'Logging · Directories','code'),
          tc(Cx+Cw//2,Cy+83,'live in-memory config','small')]

    Dx,Dy,Dw,Dh = 908,L1y+32,220,64
    p += [box(Dx,Dy,Dw,Dh,'ui'),
          tc(Dx+Dw//2,Dy+22,'WorkSpaceEditor','label-bold'),
          tc(Dx+Dw//2,Dy+42,'Edit Parameters dialog','sub')]

    p += [harr(40+Aw, Bx, Ay+Ah//2),
          harr(Bx+Bw, Cx, By+Bh//2),
          arr(Dx,Dy+18,Cx+Cw,Dy+18),    # D→C
          arr(Cx+Cw,Dy+48,Dx,Dy+48)]    # C→D

    # ── LANE 2  Config translation  (y=235, h=170) ──────────────────────────
    L2y, L2h = 235, 170
    p += ['', f'  <!-- LANE 2 -->',
          lane(20,L2y,1400,L2h,'cfg'),
          tl(36,L2y+20,'spectUI · Configuration translation  ·  workSpace.py','lane-label cfg-label')]

    Ex,Ey,Ew,Eh = 400,L2y+36,340,32
    p += [box(Ex,Ey,Ew,Eh,'cfg'),
          tc(Ex+Ew//2,Ey+21,'psd_method_from_workspace(workspace)','code')]

    Fx,Fy,Fw,Fh = 185,L2y+82,770,72
    p += [box(Fx,Fy,Fw,Fh,'cfg'),
          tl(Fx+10,Fy+20,'PsdMethod   (frozen dataclass)','label-bold'),
          tl(Fx+10,Fy+38,'algorithm  ·  bands: Dict[str, BandSpec]  ·  alpha_ci  ·  mean_convention','code'),
          tl(Fx+10,Fy+56,'welch: WelchOptions    lombscargle: LombscargleOptions    carspan: CarspanOptions','code')]

    Gx,Gy,Gw,Gh = 400,L2y+166,360,22
    p += [box(Gx,Gy,Gw,Gh,'cfg'),
          tc(Gx+Gw//2,Gy+15,'apply_psd_method_to_dataset(dataset, method)','code')]

    p += [varr(Cx+Cw//2,L1y+L1h,Ey),
          varr(Ex+Ew//2,Ey+Eh,Fy),
          varr(Fx+Fw//2,Fy+Fh,Gy)]

    # ── LANE 3  File loading  (y=417, h=112) ────────────────────────────────
    L3y, L3h = 417, 112
    p += ['', f'  <!-- LANE 3 -->',
          lane(20,L3y,1400,L3h,'fil'),
          tl(36,L3y+20,'spectUI + spectHR.DataSet.loaders  ·  File loading','lane-label fil-label')]

    Hx,Hy,Hw,Hh = 40,L3y+34,220,62
    p += [box(Hx,Hy,Hw,Hh,'fil'),
          tc(Hx+Hw//2,Hy+22,'Input files','label-bold'),
          tc(Hx+Hw//2,Hy+42,'.xdf  .nff  .csv  .pkl  …','code')]

    Ix,Iy,Iw,Ih = 278,L3y+34,185,62
    p += [box(Ix,Iy,Iw,Ih,'fil'),
          tc(Ix+Iw//2,Iy+22,'load(filename)','label-bold'),
          tc(Ix+Iw//2,Iy+42,'loaders / registry.py','sub')]

    Jx,Jy,Jw,Jh = 481,L3y+34,235,62
    p += [box(Jx,Jy,Jw,Jh,'fil'),
          tc(Jx+Jw//2,Jy+22,'PreProcessFile(workspace, file)','label-bold'),
          tc(Jx+Jw//2,Jy+42,'detect peaks · classify · segment RSP','sub')]

    Kx,Ky,Kw,Kh = 734,L3y+34,200,62
    p += [box(Kx,Ky,Kw,Kh,'fil'),
          tc(Kx+Kw//2,Ky+22,'PhysioData  ·  pkl cache','label-bold'),
          tc(Kx+Kw//2,Ky+42,'CacheDirectory','sub')]

    p += [harr(Hx+Hw,Ix,Hy+Hh//2),
          harr(Ix+Iw,Jx,Iy+Ih//2),
          harr(Jx+Jw,Kx,Jy+Jh//2)]

    # ── LANE 4  DataSet  (y=541, h=268) ─────────────────────────────────────
    L4y, L4h = 541, 268
    p += ['', f'  <!-- LANE 4 -->',
          lane(20,L4y,1400,L4h,'ds'),
          tl(36,L4y+20,'spectHR · DataSet','lane-label ds-label')]

    R1y, R1h = L4y+36, 115

    # PhysioData
    Lx,Ly,Lw,Lh = 40,R1y,270,R1h
    p += [box(Lx,Ly,Lw,Lh,'ds'),
          tc(Lx+Lw//2,Ly+17,'PhysioData','label-bold'),
          tl(Lx+8,Ly+33,'hrv_map: Dict[band, CardioSeries]','code'),
          tl(Lx+8,Ly+48,'rsp_map: Dict[name, RespirationSeries]','code'),
          tl(Lx+8,Ly+63,'timeseries · events · epochs','code'),
          tl(Lx+8,Ly+78,'active_band · basename','code'),
          tl(Lx+8,Ly+97,'epoched_parameters_table()','sub')]

    # CardioSeries / View
    Mx,My,Mw,Mh = 328,R1y,270,R1h
    p += [box(Mx,My,Mw,Mh,'ds'),
          tc(Mx+Mw//2,My+17,'CardioSeries  /  View','label-bold'),
          tl(Mx+8,My+33,'times  ·  ibi  ·  labels','code'),
          tl(Mx+8,My+48,'psd_method  ← set by UI','code'),
          tl(Mx+8,My+63,'CardioSeriesView: zero-copy epoch slice','sub'),
          tl(Mx+8,My+79,'+ CardioMetricsMixin   (time-domain)','sub'),
          tl(Mx+8,My+95,'+ CardioFrequencyMetricsMixin  (freq)','sub')]

    # RespirationSeries / View
    Nx,Ny,Nw,Nh = 616,R1y,275,R1h
    p += [box(Nx,Ny,Nw,Nh,'ds'),
          tc(Nx+Nw//2,Ny+17,'RespirationSeries  /  View','label-bold'),
          tl(Nx+8,Ny+33,'peak times  ·  labels (INH / EXH)','code'),
          tl(Nx+8,Ny+48,'phases: INH/EXH interval list per band','code'),
          tl(Nx+8,Ny+63,'RespirationSeriesView','sub'),
          tl(Nx+8,Ny+79,'.view(t0, t1)  →  phase intervals','sub')]

    # TimeSeries / Epoch
    Ox,Oy,Ow,Oh = 909,R1y,271,R1h
    p += [box(Ox,Oy,Ow,Oh,'ds'),
          tc(Ox+Ow//2,Oy+17,'TimeSeries  /  Epoch','label-bold'),
          tl(Ox+8,Oy+33,'TimeSeries: times  ·  values','code'),
          tl(Ox+8,Oy+48,'TimeSeriesView: sliced epoch view','sub'),
          tl(Ox+8,Oy+63,'StreamAccessor: data["ecg"]["rest"]','code'),
          tl(Ox+8,Oy+79,'Epoch: start · end · active','code')]

    # Public API row
    R2y, R2h = R1y+R1h+12, 46
    Px,Py,Pw,Ph = 328,R2y,852,R2h
    p += [box(Px,Py,Pw,Ph,'ds'),
          tc(Px+Pw//2,Py+16,'Public API on CardioSeries / CardioSeriesView','label-bold'),
          tc(Px+Pw//2,Py+33,
             'series.psd(with_ci=True) → PSDResult  ·  series.band_powers() → Dict[str, float]  '
             '·  .rmssd  .sdnn  .sd1  .sd2  .lf_power  .hf_power  .lf_hf_ratio  …','code')]

    p += [harr(Lx+Lw,Mx,R1y+55),
          harr(Mx+Mw,Nx,R1y+55),
          harr(Nx+Nw,Ox,R1y+55),
          varr(Mx+Mw//2,R1y+R1h,Py),
          varr(Nx+Nw//2,R1y+R1h,Py)]

    # ── LANE 5  Analysis  (y=821, h=390) ────────────────────────────────────
    L5y, L5h = 821, 392
    p += ['', f'  <!-- LANE 5 -->',
          lane(20,L5y,1400,L5h,'ana'),
          tl(36,L5y+20,'spectHR · Analysis','lane-label ana-label')]

    A1y = L5y + 38   # top of first row of analysis boxes

    # --- PSD sub-group (x=40, w=420) ---
    # PSDEngine header
    PEx,PEy,PEw,PEh = 40,A1y,420,28
    p += [box(PEx,PEy,PEw,PEh,'ana'),
          tc(PEx+PEw//2,PEy+19,'PSDEngine  ·  dispatch on  method.algorithm','label-bold')]

    # 4 backends in 2×2 grid
    backends=[('compute_welch_psd','WelchOptions'),
              ('compute_lombscargle_psd','LombscargleOptions'),
              ('compute_carspan_psd','CarspanOptions'),
              ('compute_carspan_psd_strict','CARSPAN-strict preset')]
    BBw,BBh,BBg = 204,52,8
    for i,(nm,opt) in enumerate(backends):
        col,row=i%2,i//2
        bx=40+col*(BBw+BBg); by=A1y+36+row*(BBh+BBg)
        p += [box(bx,by,BBw,BBh,'ana'),
              tc(bx+BBw//2,by+20,nm,'label'),
              tc(bx+BBw//2,by+38,opt,'code')]

    PRy = A1y+36+2*(BBh+BBg)+4
    PRx,PRw,PRh = 40,420,28
    p += [box(PRx,PRy,PRw,PRh,'ana'),
          tc(PRx+PRw//2,PRy+19,'PSDResult:  freqs  ·  power  ·  ci_lower  ·  ci_upper  ·  unit  ·  method','code')]

    p += [varr(PEx+PEw//2,PEy+PEh,A1y+36),
          varr(PRx+PRw//2,A1y+36+2*(BBh+BBg),PRy)]

    # --- Profile sub-group (x=480, w=300) ---
    PFx,PFy,PFw,PFh = 480,A1y,300,56
    p += [box(PFx,PFy,PFw,PFh,'ana'),
          tc(PFx+PFw//2,PFy+20,'compute_band_power_profile','label-bold'),
          tc(PFx+PFw//2,PFy+40,'sliding-window PSD integration','sub')]
    PFRy=PFy+64; PFRh=28
    p += [box(PFx,PFRy,PFw,PFRh,'ana'),
          tc(PFx+PFw//2,PFRy+19,'ProfileResult: timestamps · band_power[N_bands × N_windows]','code')]
    p += [varr(PFx+PFw//2,PFy+PFh,PFRy)]

    # --- Transfer sub-group (x=800, w=580) ---
    TF1x,TF1y,TF1w,TF1h = 800,A1y,280,56
    TF2x,TF2y,TF2w,TF2h = 1090,A1y,290,56
    p += [box(TF1x,TF1y,TF1w,TF1h,'ana'),
          tc(TF1x+TF1w//2,TF1y+20,'compute_transfer','label-bold'),
          tc(TF1x+TF1w//2,TF1y+40,'per-epoch Bode plot','sub'),
          box(TF2x,TF2y,TF2w,TF2h,'ana'),
          tc(TF2x+TF2w//2,TF2y+20,'compute_transfer_profile','label-bold'),
          tc(TF2x+TF2w//2,TF2y+40,'sliding-window transfer','sub')]
    TFRy=TF1y+64; TFRx,TFRw,TFRh = 800,580,28
    p += [box(TFRx,TFRy,TFRw,TFRh,'ana'),
          tc(TFRx+TFRw//2,TFRy+19,
             'TransferResult / TransferProfileResult:  freqs  ·  modulus  ·  phase  ·  coherence  ·  band summaries','code')]
    p += [varr(TF1x+TF1w//2,TF1y+TF1h,TFRy),
          varr(TF2x+TF2w//2,TF2y+TF2h,TFRy)]

    # --- Row 2: Metrics + RSA ---
    # Place after deepest element in row 1 (PSD group)
    PSD_bottom = PRy + PRh   # bottom of PSDResult
    R2Ay = PSD_bottom + 14

    MRx,MRy,MRw,MRh = 40,R2Ay,600,88
    p += [box(MRx,MRy,MRw,MRh,'ana'),
          tl(MRx+10,MRy+18,'@epoch_metric  registry','label-bold'),
          tl(MRx+10,MRy+35,'time_metrics:   count  mean  median  rmssd  sdnn  sdsd  sd1  sd2  pnn50  …','code'),
          tl(MRx+10,MRy+51,'freq_metrics:   fullrange  vlf_power  lf_power  hf_power  lf_hf_ratio','code'),
          tl(MRx+10,MRy+67,'bp_metrics:     bp_sbp  bp_dbp  bp_pp  bp_map  resp_mvo  resp_svo  rsa  rsa0','code')]

    RSAx,RSAy,RSAw,RSAh = 658,R2Ay,380,88
    p += [box(RSAx,RSAy,RSAw,RSAh,'ana'),
          tc(RSAx+RSAw//2,RSAy+20,'grossman_rsa_per_breath()','label-bold'),
          tc(RSAx+RSAw//2,RSAy+38,'peak-to-valley RSA per INH/EXH cycle','sub'),
          tc(RSAx+RSAw//2,RSAy+56,'rsa_lag_s: autonomic conduction delay (default 1.0 s)','sub'),
          tc(RSAx+RSAw//2,RSAy+74,'→  rsa[N_br]  ·  rsa0[N_br]','code')]

    ECx,ECy,ECw,ECh = 40,R2Ay+100,998,36
    p += [box(ECx,ECy,ECw,ECh,'ana'),
          tc(ECx+ECw//2,ECy+14,'EpochContext','label-bold'),
          tc(ECx+ECw//2,ECy+29,
             'per-epoch cache:  HRV metrics  ·  PSD  ·  band powers  ·  transfer  ·  profile  ·  RSA  ·  BP  →  feeds export','sub')]

    p += [varr(MRx+MRw//2,MRy+MRh,ECy),
          varr(RSAx+RSAw//2,RSAy+RSAh,ECy)]

    # ── LANE 6  Export  (y = L5y+L5h+12, h=130) ─────────────────────────────
    L6y = L5y + L5h + 12
    L6h = 130
    p += ['', f'  <!-- LANE 6 -->',
          lane(20,L6y,1400,L6h,'exp'),
          tl(36,L6y+20,'spectUI · Export  ·  ParametersPlotWidget','lane-label exp-label')]

    EPTx,EPTy,EPTw,EPTh = 40,L6y+36,290,64
    p += [box(EPTx,EPTy,EPTw,EPTh,'exp'),
          tc(EPTx+EPTw//2,EPTy+22,'epoched_parameters_table()','label-bold'),
          tc(EPTx+EPTw//2,EPTy+44,'→  labels  ·  cols  ·  values (N×M)','code')]

    CSVx,CSVy,CSVw,CSVh = 348,L6y+36,190,64
    p += [box(CSVx,CSVy,CSVw,CSVh,'exp'),
          tc(CSVx+CSVw//2,CSVy+22,'{basename}.csv','label-bold'),
          tc(CSVx+CSVw//2,CSVy+42,'scalars · one row per epoch','sub')]

    CEDx,CEDy,CEDw,CEDh = 556,L6y+36,280,64
    p += [box(CEDx,CEDy,CEDw,CEDh,'exp'),
          tc(CEDx+CEDw//2,CEDy+22,'_collect_epoch_data()','label-bold'),
          tc(CEDx+CEDw//2,CEDy+42,'psd · profile · transfer · respiration','sub')]

    H5x,H5y,H5w,H5h = 854,L6y+36,210,64
    p += [box(H5x,H5y,H5w,H5h,'exp'),
          tc(H5x+H5w//2,H5y+22,'{basename}.h5','label-bold'),
          tc(H5x+H5w//2,H5y+42,'full arrays · HDF5 groups per epoch','sub')]

    p += [harr(EPTx+EPTw,CSVx,EPTy+EPTh//2),
          harr(CSVx+CSVw,CEDx,CSVy+CSVh//2),
          harr(CEDx+CEDw,H5x,CEDy+CEDh//2)]

    # ── LANE 7  Plot widgets  (y = L6y+L6h+12, h=210) ───────────────────────
    L7y = L6y + L6h + 12
    L7h = 210
    p += ['', f'  <!-- LANE 7 -->',
          lane(20,L7y,1400,L7h,'ui'),
          tl(36,L7y+20,'spectUI · Plot widgets','lane-label ui-label')]

    # Row 1: 5 timeline widgets
    TLw,TLh,TLg = 262,58,8
    tl_widgets=[('PrepPlotWidget','Preprocessing'),
                ('HRPlotWidget','HR Series  +  RSA overlay'),
                ('BPPlotWidget','Blood Pressure'),
                ('PoincarePlotWidget','Poincaré'),
                ('EpochPlotWidget','Epochs')]
    row1y = L7y+38
    for i,(nm,sb) in enumerate(tl_widgets):
        bx=40+i*(TLw+TLg)
        p += [box(bx,row1y,TLw,TLh,'ui'),
              tc(bx+TLw//2,row1y+22,nm,'label-bold'),
              tc(bx+TLw//2,row1y+40,sb,'sub')]

    # Row 2: 7 analysis widgets
    ANw,ANh,ANg = 185,60,8
    an_widgets=[('PSDPlotWidget','PSD'),
                ('SpectrogramPlotWidget','Spectrogram'),
                ('Spectrogram3DPlotWidget','3D Spectrogram'),
                ('TransferPlotWidget','Transfer  (Bode)'),
                ('TransferProfilePlotWidget','Transfer Profile'),
                ('ProfilePlotWidget','Profiles'),
                ('ParametersPlotWidget','Parameters + Export')]
    row2y = row1y + TLh + 10
    for i,(nm,sb) in enumerate(an_widgets):
        bx=40+i*(ANw+ANg)
        p += [box(bx,row2y,ANw,ANh,'ui'),
              tc(bx+ANw//2,row2y+22,nm,'label-bold'),
              tc(bx+ANw//2,row2y+40,sb,'sub')]

    # ── LEGEND ───────────────────────────────────────────────────────────────
    LLy = L7y + L7h + 18
    legend=[('ui','spectUI, workspace I/O · configuration · plot widgets · export'),
            ('cfg','Configuration translation, PsdMethod · psd_method_from_workspace'),
            ('fil','File loading, loaders (XDF, NFF, CSV, PKL)  ·  PreProcessFile'),
            ('ds','spectHR · DataSet, PhysioData · CardioSeries · RespirationSeries · TimeSeries · Epoch'),
            ('ana','spectHR · Analysis, PSD backends · Transfer · Profiles · Metrics · RSA · EpochContext'),
            ('exp','Export, CSV (scalar metrics per epoch) + HDF5 (full arrays)')]
    for i,(cls,lbl) in enumerate(legend):
        col,row=i%3,i//3
        lx=36+col*465; ly=LLy+26+row*28
        p += [f'<rect x="{lx}" y="{ly}" width="16" height="16" class="box-{cls}" rx="3"/>',
              tl(lx+22,ly+12,lbl,'sub')]

    p += [tl(36,LLy+96,'Dependency rule:  spectUI imports from spectHR  ·  spectHR has zero module-level configuration state.','sub'),
          tl(36,LLy+112,'All knobs travel as parameters; PsdMethod is the single named bundle the UI hands across the boundary.','sub')]

    # ── INTER-LANE ARROWS ────────────────────────────────────────────────────
    p += ['', '  <!-- inter-lane arrows -->',
          # L1→L2: workspace dict → psd_method_from_workspace
          varr(Cx+Cw//2, L1y+L1h, Ey),
          # L2→L4: apply_psd_method_to_dataset → CardioSeries.psd_method
          arr(Gx+Gw//2, L2y+L2h, Mx+Mw//2, R1y),
          tl(Gx+Gw//2+4,(L2y+L2h+R1y)//2,'sets .psd_method','arr-label'),
          # L3→L4: pkl cache → PhysioData
          arr(Kx+Kw//2, L3y+L3h, Lx+Lw//2, R1y),
          # L4→L5: CardioSeries/View → PSDEngine
          arr(Mx+Mw//2, L4y+L4h, PEx+PEw//2, PEy),
          # L4→L5: CardioSeries/View → Profiles
          arr(Px+Pw//2, L4y+L4h, PFx+PFw//2, PFy),
          # L4→L5: RespirationSeries → Transfer
          arr(Nx+Nw//2, L4y+L4h, TF1x+TF1w//2, TF1y),
          # L4→L5: RespirationSeries → RSA
          arr(Nx+Nw-10, L4y+L4h, RSAx+RSAw//2, RSAy),
          # L5→L6: EpochContext → export
          arr(ECx+ECw//4,   L5y+L5h, EPTx+EPTw//2, EPTy),
          arr(ECx+ECw*3//4, L5y+L5h, CEDx+CEDw//2, CEDy),
          # L5→L7: PSDResult → PSDPlotWidget (skip lane 6)
          arr(PRx+PRw//4, L5y+L5h, 40+ANw//2, row2y),
          # L5→L7: Transfer → TransferPlotWidget
          arr(TFRx+TFRw//2, L5y+L5h, 40+3*(ANw+ANg)+ANw//2, row2y),
          # L6→L7: csv → ParametersPlotWidget
          arr(CSVx+CSVw//2, L6y+L6h, 40+6*(ANw+ANg)+ANw//2, row2y),
    ]

    p.append('</svg>')
    return '\n'.join(p)

if __name__ == '__main__':
    svg = build()
    OUT.write_text(svg, encoding='utf-8')
    print(f'Saved {OUT}  ({len(svg):,} chars, viewBox 0 0 {W} {H})')
