[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Output = Join-Path $PSScriptRoot 'SecureCloud_Demo_Presentation.pptx'
$PdfOutput = Join-Path $PSScriptRoot 'SecureCloud_Demo_Presentation.pdf'
$PreviewRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'runtime\demo-deck-preview'
New-Item -ItemType Directory -Force -Path $PreviewRoot | Out-Null

function Rgb([int]$r, [int]$g, [int]$b) { return $r + ($g * 256) + ($b * 65536) }

$C = @{
    Ink = Rgb 18 32 51
    Muted = Rgb 83 99 117
    Blue = Rgb 0 120 212
    BlueDark = Rgb 0 78 140
    BluePale = Rgb 232 244 252
    Green = Rgb 16 124 65
    GreenPale = Rgb 232 246 237
    Amber = Rgb 176 96 0
    AmberPale = Rgb 255 244 206
    Red = Rgb 196 43 28
    RedPale = Rgb 253 236 234
    Line = Rgb 213 220 227
    Panel = Rgb 246 248 250
    White = Rgb 255 255 255
}

$pp = New-Object -ComObject PowerPoint.Application
$pp.Visible = -1
$deck = $pp.Presentations.Add()
$deck.PageSetup.SlideWidth = 960
$deck.PageSetup.SlideHeight = 540

function Add-Text {
    param($Slide, [string]$Text, [double]$Left, [double]$Top, [double]$Width, [double]$Height,
        [double]$Size = 18, [int]$Colour = $C.Ink, [switch]$Bold, [string]$Font = 'Aptos',
        [int]$Align = 1, [switch]$Italic)
    $shape = $Slide.Shapes.AddTextbox(1, $Left, $Top, $Width, $Height)
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 0
    $shape.TextFrame.MarginBottom = 0
    $shape.TextFrame.WordWrap = -1
    $shape.TextFrame.TextRange.Text = $Text
    $shape.TextFrame.TextRange.Font.Name = $Font
    $shape.TextFrame.TextRange.Font.Size = $Size
    $shape.TextFrame.TextRange.Font.Color.RGB = $Colour
    $shape.TextFrame.TextRange.Font.Bold = $(if ($Bold) { -1 } else { 0 })
    $shape.TextFrame.TextRange.Font.Italic = $(if ($Italic) { -1 } else { 0 })
    $shape.TextFrame.TextRange.ParagraphFormat.Alignment = $Align
    return $shape
}

function Add-Box {
    param($Slide, [double]$Left, [double]$Top, [double]$Width, [double]$Height,
        [int]$Fill = $C.White, [int]$Stroke = $C.Line, [double]$Radius = 1)
    $shape = $Slide.Shapes.AddShape(5, $Left, $Top, $Width, $Height)
    $shape.Fill.Solid()
    $shape.Fill.ForeColor.RGB = $Fill
    $shape.Line.ForeColor.RGB = $Stroke
    $shape.Line.Weight = $Radius
    return $shape
}

function Add-Line {
    param($Slide, [double]$X1, [double]$Y1, [double]$X2, [double]$Y2,
        [int]$Colour = $C.Line, [double]$Weight = 1, [switch]$Arrow)
    $line = $Slide.Shapes.AddLine($X1, $Y1, $X2, $Y2)
    $line.Line.ForeColor.RGB = $Colour
    $line.Line.Weight = $Weight
    if ($Arrow) { $line.Line.EndArrowheadStyle = 3 }
    return $line
}

function Add-Slide {
    param([string]$Title, [string]$Kicker = 'SECURECLOUD DEMO')
    $slide = $deck.Slides.Add($deck.Slides.Count + 1, 12)
    $slide.FollowMasterBackground = 0
    $slide.Background.Fill.Solid()
    $slide.Background.Fill.ForeColor.RGB = $C.White
    [void](Add-Text $slide $Kicker 54 24 350 18 9 $C.Blue -Bold)
    [void](Add-Text $slide $Title 54 47 850 44 26 $C.Ink -Bold)
    [void](Add-Line $slide 54 96 906 96 $C.Line 1)
    [void](Add-Text $slide ([string]$slide.SlideIndex) 900 506 20 14 8 $C.Muted -Align 3)
    return $slide
}

function Add-Notes($Slide, [string]$Text) {
    try {
        $placeholder = $Slide.NotesPage.Shapes.Placeholders.Item(2)
        $placeholder.TextFrame.TextRange.Text = $Text
    } catch {}
}

function Add-Metric {
    param($Slide, [string]$Value, [string]$Label, [double]$Left, [double]$Top, [int]$Colour = $C.Blue)
    [void](Add-Text $Slide $Value $Left $Top 150 38 28 $Colour -Bold)
    [void](Add-Text $Slide $Label $Left ($Top + 38) 160 34 11 $C.Muted)
}

# 1 - Title
$s = $deck.Slides.Add(1, 12)
$s.FollowMasterBackground = 0
$s.Background.Fill.Solid(); $s.Background.Fill.ForeColor.RGB = $C.White
$accent = $s.Shapes.AddShape(1, 0, 0, 16, 540); $accent.Fill.ForeColor.RGB = $C.Blue; $accent.Line.Visible = 0
[void](Add-Text $s 'SECURECLOUD' 70 64 400 22 12 $C.Blue -Bold)
[void](Add-Text $s 'SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation' 70 104 770 112 31 $C.Ink -Bold)
[void](Add-Text $s 'Live demonstration | Final Year Project' 72 232 500 30 17 $C.Muted)
[void](Add-Line $s 70 286 890 286 $C.Line 1)
[void](Add-Text $s 'Aditya Rajendra Melavanki | Abhishek Suryanarayana Bhat | Aditya B N | Girish R V' 70 316 820 28 13 $C.Ink -Bold)
[void](Add-Text $s 'Dr. S. Anthoniraj  |  School of Computer Science and Engineering, JAIN (Deemed-to-be University)' 70 352 820 44 12 $C.Muted)
$tag = Add-Box $s 70 438 450 44 $C.BluePale $C.Blue
[void](Add-Text $s 'DEPLOY  ->  OBSERVE  ->  DETECT  ->  CONTAIN  ->  RESTORE' 88 451 420 18 11 $C.BlueDark -Bold)
Add-Notes $s 'Introduce SecureCloud as an Azure-like self-service private-cloud prototype on Kubernetes. State that the research focus is runtime zero-trust enforcement and temporal-graph detection.'

# 2 - Problem
$s = Add-Slide 'Why SecureCloud exists'
[void](Add-Text $s 'A valid workload can still behave abnormally after compromise.' 54 120 820 36 20 $C.Ink -Bold)
$columns = @(
    @('01','Provision','Users need bounded self-service deployment without raw Kubernetes access.'),
    @('02','Enforce','Static policy must deny undeclared tenant and service paths.'),
    @('03','Respond','The platform must connect evidence to quarantine and reversible recovery.')
)
for ($i=0; $i -lt 3; $i++) {
    $left = 54 + ($i * 292)
    if ($i -gt 0) { [void](Add-Line $s ($left - 22) 184 ($left - 22) 374 $C.Line 1) }
    [void](Add-Text $s $columns[$i][0] $left 184 50 30 21 $C.Blue -Bold)
    [void](Add-Text $s $columns[$i][1] $left 228 240 28 17 $C.Ink -Bold)
    [void](Add-Text $s $columns[$i][2] $left 270 245 92 13 $C.Muted)
}
$boundary = Add-Box $s 54 414 852 60 $C.Panel $C.Line
[void](Add-Text $s 'Scope boundary' 72 429 120 18 10 $C.Blue -Bold)
[void](Add-Text $s 'An evaluated Kubernetes prototype - not a public-cloud replacement, hypervisor, or production isolation platform.' 194 426 680 30 13 $C.Ink)
Add-Notes $s 'Frame the problem as post-compromise lateral movement in organisation-managed workloads. Do not claim that public clouds casually expose customers to each other.'

# 3 - Running system
$s = Add-Slide 'What is running in the lab'
Add-Metric $s '2' 'active tenants' 54 122 $C.Blue
Add-Metric $s '15' 'observed workloads' 214 122 $C.Green
Add-Metric $s '24k+' 'live Hubble flows*' 394 122 $C.Amber
Add-Metric $s '100' 'automated tests' 594 122 $C.BlueDark
[void](Add-Text $s '*Flow count changes during the live demonstration.' 54 202 460 18 9 $C.Muted -Italic)
$nodes = @(
    @('Portal','React + TypeScript',54,$C.BluePale,$C.Blue),
    @('Management API','FastAPI + SQLite',265,$C.Panel,$C.BlueDark),
    @('Kubernetes lab','K3s + Cilium + Hubble',500,$C.GreenPale,$C.Green),
    @('Risk engine','GConvGRU + EWMA',735,$C.AmberPale,$C.Amber)
)
foreach ($node in $nodes) {
    [void](Add-Box $s $node[2] 282 172 100 $node[3] $node[4] 1.2)
    [void](Add-Text $s $node[0] ($node[2]+14) 300 144 22 15 $C.Ink -Bold -Align 2)
    [void](Add-Text $s $node[1] ($node[2]+14) 332 144 34 10 $C.Muted -Align 2)
}
for ($i=0; $i -lt 3; $i++) { [void](Add-Line $s (226 + ($i*235)) 332 (257 + ($i*235)) 332 $C.Blue 1.8 -Arrow) }
[void](Add-Text $s 'Portal :4174     API :8000     Retail :8094     Vendor :8095' 54 430 852 22 11 $C.Muted -Align 2)
Add-Notes $s 'Show that the portal is backed by the real management API. RetailCo runs 12 Online Boutique services; FacilitiesVendor runs web, API, and PostgreSQL.'

# 4 - Architecture
$s = Add-Slide 'Two connected planes, one demonstrable loop'
[void](Add-Text $s 'MANAGEMENT PLANE' 54 120 190 18 10 $C.Blue -Bold)
[void](Add-Line $s 54 142 906 142 $C.Blue 1.5)
$management = @(@('Portal','tenant + catalog'),@('API','authorization'),@('Store','desired + observed'),@('Adapter','bounded manifests'))
for ($i=0; $i -lt $management.Count; $i++) {
    $x = 54 + ($i * 215)
    [void](Add-Box $s $x 165 170 64 $C.White $C.Line)
    [void](Add-Text $s $management[$i][0] ($x+12) 177 146 18 14 $C.Ink -Bold -Align 2)
    [void](Add-Text $s $management[$i][1] ($x+12) 201 146 15 9 $C.Muted -Align 2)
    if ($i -lt 3) { [void](Add-Line $s ($x+172) 197 ($x+208) 197 $C.Blue 1.5 -Arrow) }
}
[void](Add-Text $s 'SECURITY PLANE' 54 270 190 18 10 $C.Green -Bold)
[void](Add-Line $s 54 292 906 292 $C.Green 1.5)
$security = @(@('Cilium','policy verdicts'),@('Hubble','runtime flows'),@('30 s graph','stable identities'),@('GNN + EWMA','risk evidence'),@('Incident','quarantine / restore'))
for ($i=0; $i -lt $security.Count; $i++) {
    $x = 54 + ($i * 174)
    [void](Add-Box $s $x 316 144 66 $C.White $C.Line)
    [void](Add-Text $s $security[$i][0] ($x+8) 329 128 18 13 $C.Ink -Bold -Align 2)
    [void](Add-Text $s $security[$i][1] ($x+8) 353 128 17 9 $C.Muted -Align 2)
    if ($i -lt 4) { [void](Add-Line $s ($x+146) 349 ($x+169) 349 $C.Green 1.5 -Arrow) }
}
[void](Add-Line $s 824 229 824 312 $C.BlueDark 1.8 -Arrow)
[void](Add-Text $s 'Kubernetes supplies orchestration; SecureCloud supplies safe intent, evidence, and response.' 54 430 852 34 14 $C.Ink -Bold -Align 2)
Add-Notes $s 'Explain the separation between management and security. Users never submit raw YAML. Detection creates evidence; only an authorized operation changes policy.'

# 5 - Scenario
$s = Add-Slide 'Demo scenario: compromised vendor access'
[void](Add-Text $s 'RetailCo' 74 126 250 26 19 $C.Ink -Bold)
[void](Add-Text $s '12-service shopping application' 74 157 250 20 11 $C.Muted)
[void](Add-Text $s 'FacilitiesVendor' 654 126 240 26 19 $C.Ink -Bold -Align 3)
[void](Add-Text $s 'web | API | PostgreSQL' 654 157 240 20 11 $C.Muted -Align 3)
$retail = Add-Box $s 54 196 300 172 $C.BluePale $C.Blue
$vendor = Add-Box $s 606 196 300 172 $C.GreenPale $C.Green
[void](Add-Text $s 'frontend -> catalogue -> cart -> checkout' 74 218 260 28 12 $C.Ink -Bold -Align 2)
[void](Add-Text $s "payment | shipping | recommendation`nplus supporting services" 74 268 260 48 11 $C.Muted -Align 2)
[void](Add-Text $s 'vendor-web -> vendor-api -> database' 626 218 260 28 12 $C.Ink -Bold -Align 2)
[void](Add-Text $s "ordinary maintenance activity`nthen abnormal cross-tenant use" 626 268 260 48 11 $C.Muted -Align 2)
[void](Add-Line $s 594 250 366 250 $C.Red 2.2 -Arrow)
[void](Add-Text $s 'abnormal connection' 388 224 184 18 10 $C.Red -Bold -Align 2)
[void](Add-Text $s '1. Learn normal traffic   2. Score abnormal edge   3. Corroborate with policy facts   4. Quarantine source' 72 414 816 36 13 $C.Ink -Bold -Align 2)
[void](Add-Text $s 'All traffic stays inside the project-owned lab.' 54 474 852 18 10 $C.Muted -Italic -Align 2)
Add-Notes $s 'This is inspired by the vendor-access problem documented in the 2013 Target breach, not a reconstruction of the uncertain historical attack path.'

# 6 - Runbook
$s = Add-Slide 'Live demo: six steps'
$steps = @(
    @('1','Inspect','RetailCo + FacilitiesVendor and 15 observed workloads'),
    @('2','Use apps','Browse the shop and create a vendor work order'),
    @('3','Observe','Show topology and live Hubble evidence'),
    @('4','Detect','Compare GNN, accumulated risk, baseline, threshold'),
    @('5','Contain','Open the incident and quarantine the source'),
    @('6','Recover','Restore policy and verify the approved path')
)
for ($i=0; $i -lt $steps.Count; $i++) {
    $row = [math]::Floor($i / 3)
    $col = $i % 3
    $x = 54 + ($col * 292)
    $y = 126 + ($row * 154)
    [void](Add-Text $s $steps[$i][0] $x $y 36 30 20 $C.Blue -Bold)
    [void](Add-Text $s $steps[$i][1] ($x+48) ($y+2) 190 24 16 $C.Ink -Bold)
    [void](Add-Text $s $steps[$i][2] ($x+48) ($y+38) 218 64 11 $C.Muted)
    if ($col -lt 2) { [void](Add-Line $s ($x+255) ($y+16) ($x+282) ($y+16) $C.Line 1.5 -Arrow) }
}
$cue = Add-Box $s 54 432 852 48 $C.Panel $C.Line
[void](Add-Text $s 'Reviewer cue: policy prevents explicitly forbidden traffic; the temporal model examines abnormal behaviour over time.' 72 446 816 24 12 $C.Ink -Bold -Align 2)
Add-Notes $s 'Keep the live portion under six minutes. Do not spend time on catalog creation unless asked; begin from the already running two-tenant lab.'

# 7 - Risk engine
$s = Add-Slide 'How the temporal risk decision works'
[void](Add-Text $s 'risk(t) = alpha * anomaly(t) + (1 - alpha) * risk(t-1)' 54 118 510 30 17 $C.BlueDark -Bold)
[void](Add-Text $s 'The GNN asks "is this edge unusual?" EWMA asks "is the source staying risky?"' 54 154 800 26 12 $C.Muted)
$headers = @('Connection','GNN','Accum. / threshold','Baseline','Decision')
$widths = @(330,90,180,105,100)
$x = 54
for ($i=0; $i -lt $headers.Count; $i++) {
    [void](Add-Text $s $headers[$i] $x 210 $widths[$i] 20 10 $C.Muted -Bold)
    $x += $widths[$i]
}
[void](Add-Line $s 54 236 906 236 $C.Line 1)
$riskRows = @(
    @('vendor-api -> frontend','1.000','1.000 / 0.500','0.917','Respond'),
    @('productcatalogservice -> frontend','1.000','0.999 / 0.500','0.667','Respond'),
    @('redis-cart -> cartservice','0.729','0.729 / 0.500','0.182','Observe'),
    @('loadgenerator -> frontend','1.000','1.000 / 0.500','0.091','Observe')
)
for ($r=0; $r -lt $riskRows.Count; $r++) {
    $y = 250 + ($r * 42)
    $x = 54
    for ($i=0; $i -lt 5; $i++) {
        $colour = if ($i -eq 4 -and $riskRows[$r][$i] -eq 'Respond') { $C.Red } elseif ($i -eq 4) { $C.Amber } else { $C.Ink }
        $cell = Add-Text $s $riskRows[$r][$i] $x $y $widths[$i] 22 11 $colour
        if ($i -eq 4) { $cell.TextFrame.TextRange.Font.Bold = -1 }
        $x += $widths[$i]
    }
    [void](Add-Line $s 54 ($y+30) 906 ($y+30) $C.Line 0.7)
}
[void](Add-Text $s 'High score alone -> Observe     |     Persistent risk + independent policy fact -> Recommend response' 54 440 852 28 13 $C.Ink -Bold -Align 2)
Add-Notes $s 'Emphasize that the model does not directly write Cilium policy. A high model score alone remains reviewable evidence; corroboration is required for a response recommendation.'

# 8 - Results
$s = Add-Slide 'Evaluation: temporal model versus baseline'
[void](Add-Text $s '1,800 scenario runs | 12 scenarios | 30 repetitions | 5 seeds' 54 118 600 26 14 $C.Ink -Bold)
$metrics = @(
    @('Precision',1.000,0.923),
    @('Recall',0.846,0.923),
    @('F1',0.917,0.923),
    @('FPR',0.000,0.091),
    @('Average precision',0.880,0.771)
)
$baseX = 54; $baseY = 190; $chartW = 540
for ($i=0; $i -lt $metrics.Count; $i++) {
    $y = $baseY + ($i * 52)
    [void](Add-Text $s $metrics[$i][0] $baseX $y 120 18 10 $C.Muted -Bold)
    $baselineW = 260 * $metrics[$i][1]
    $temporalW = 260 * $metrics[$i][2]
    $b1 = $s.Shapes.AddShape(1, $baseX+130, $y, $baselineW, 10); $b1.Fill.ForeColor.RGB=$C.Muted; $b1.Line.Visible=0
    $b2 = $s.Shapes.AddShape(1, $baseX+130, $y+16, $temporalW, 10); $b2.Fill.ForeColor.RGB=$C.Blue; $b2.Line.Visible=0
    [void](Add-Text $s ('{0:N3}' -f $metrics[$i][1]) ($baseX+405) ($y-3) 50 14 9 $C.Muted)
    [void](Add-Text $s ('{0:N3}' -f $metrics[$i][2]) ($baseX+463) ($y+13) 50 14 9 $C.Blue -Bold)
}
[void](Add-Text $s 'Baseline' 54 462 100 18 9 $C.Muted)
[void](Add-Text $s 'Temporal' 160 462 100 18 9 $C.Blue -Bold)
$callout = Add-Box $s 638 176 268 214 $C.BluePale $C.Blue 1.3
[void](Add-Text $s 'Key gain' 660 198 220 20 11 $C.Blue -Bold)
[void](Add-Text $s 'Vertical port scan' 660 232 220 28 18 $C.Ink -Bold)
[void](Add-Text $s "Baseline recall   0.000`nTemporal recall  1.000" 660 278 220 56 13 $C.Ink)
[void](Add-Text $s 'Trade-off: higher recall, but FPR rises to 0.091 and ranking quality falls.' 638 414 268 58 11 $C.Muted)
Add-Notes $s 'Do not claim universal superiority. The temporal model improved recall and found the vertical scan, but the baseline had zero false positives and higher average precision.'

# 9 - Evidence boundary
$s = Add-Slide 'What is verified - and what remains'
[void](Add-Text $s 'VERIFIED' 54 124 250 18 10 $C.Green -Bold)
[void](Add-Text $s "- 76 backend tests + 24 frontend tests`n- Two real tenants and 15 observed workloads`n- Live Cilium verdicts and Hubble ingestion`n- Incident, quarantine, pod replacement, restore`n- Five-seed offline temporal evaluation" 54 158 390 210 14 $C.Ink)
[void](Add-Line $s 480 124 480 410 $C.Line 1)
[void](Add-Text $s 'NOT YET CLAIMED' 522 124 300 18 10 $C.Amber -Bold)
[void](Add-Text $s "- Production-scale generalisation`n- Public-cloud isolation replacement`n- Live predictive lead-time distribution`n- CPU and memory overhead benchmark`n- Production automatic containment safety" 522 158 384 210 14 $C.Ink)
$honesty = Add-Box $s 54 424 852 54 $C.Panel $C.Line
[void](Add-Text $s 'Demo rule: show positive controls, explicit verdicts, and observed state - never infer enforcement from a timeout.' 72 440 816 25 12 $C.Ink -Bold -Align 2)
Add-Notes $s 'Use this slide if reviewers challenge the claims. The project has strong prototype evidence but still has explicit external-validity and overhead limitations.'

# 10 - Close
$s = Add-Slide 'SecureCloud closes the loop' 'FINAL TAKEAWAY'
[void](Add-Text $s 'Deploy' 78 150 126 30 21 $C.Blue -Bold -Align 2)
[void](Add-Text $s 'Observe' 246 150 126 30 21 $C.Blue -Bold -Align 2)
[void](Add-Text $s 'Detect' 414 150 126 30 21 $C.Blue -Bold -Align 2)
[void](Add-Text $s 'Contain' 582 150 126 30 21 $C.Red -Bold -Align 2)
[void](Add-Text $s 'Restore' 750 150 126 30 21 $C.Green -Bold -Align 2)
for ($i=0; $i -lt 4; $i++) { [void](Add-Line $s (204+$i*168) 165 (238+$i*168) 165 $C.Line 2 -Arrow) }
[void](Add-Text $s 'Bounded self-service cloud management plus evidence-driven zero-trust response.' 110 236 740 52 22 $C.Ink -Bold -Align 2)
[void](Add-Text $s 'Portal  http://127.0.0.1:4174     |     API  http://127.0.0.1:8000/docs' 110 326 740 28 12 $C.Muted -Align 2)
[void](Add-Text $s 'Questions?' 54 416 852 44 30 $C.BlueDark -Bold -Align 2)
Add-Notes $s 'End on the connected contribution: the portal manages bounded workloads, while the security plane observes, scores, contains, and restores them.'

# Save and export.
$deck.SaveAs($Output, 24)
$deck.SaveAs($PdfOutput, 32)
foreach ($slide in $deck.Slides) {
    $slide.Export((Join-Path $PreviewRoot ("slide-{0:D2}.png" -f $slide.SlideIndex)), 'PNG', 1600, 900)
}
$deck.Close()
$pp.Quit()
[Runtime.InteropServices.Marshal]::ReleaseComObject($deck) | Out-Null
[Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
Write-Output $Output
Write-Output $PdfOutput
Write-Output $PreviewRoot
