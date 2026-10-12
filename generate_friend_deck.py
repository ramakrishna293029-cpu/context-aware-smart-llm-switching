"""
Generator for the 11-Slide Streamlined Presentation:
'Design Project Context of Smart llm switching for Cost and Performance Optimization.pptx'

Strictly follows the slide count, sequence, layout, and visual flow of the friend's presentation:
Slide 1: Title of the Project
Slide 2: INDEX TABLE
Slide 3: INTRODUCTION
Slide 4: DIAGRAM (Overall System Diagram - 7-Stage Flowchart)
Slide 5: LITERATURE REVIEW TABLE (Papers 1 to 5)
Slide 6: LITERATURE REVIEW TABLE (Papers 6 to 10)
Slide 7: GAP ANALYSIS (Part 1)
Slide 8: GAP ANALYSIS (Part 2 - Overall Gap in Existing Technology)
Slide 9: CONCLUSION
Slide 10: REFERENCES (Papers 1 to 6)
Slide 11: REFERENCES (Papers 7 to 10)
"""

import os
import pptx
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# 16:9 Widescreen dimensions
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# Color Palette matching the friend's template
NAVY_PRIMARY   = RGBColor(15, 44, 89)      # #0F2C59 - Deep Navy
BLUE_HEADER    = RGBColor(47, 101, 156)    # #2F659C - Friend's Table Blue Header
BLUE_ACCENT    = RGBColor(46, 117, 182)    # #2E75B6 - Royal Accent Blue
SLATE_DARK     = RGBColor(26, 26, 26)      # #1A1A1A - Crisp Text Charcoal
SLATE_MUTED    = RGBColor(89, 89, 89)      # #595959 - Secondary text
CARD_BORDER    = RGBColor(205, 218, 232)   # #CDDAE8 - Border Line
HEADER_TEXT    = RGBColor(255, 255, 255)   # White
ROW_ALT_BG     = RGBColor(232, 238, 245)   # #E8EEF5 - Alternating Row Fill
STAGE_BG       = RGBColor(217, 225, 242)   # #D9E1F2 - Diagram Stage Header Fill
WHITE          = RGBColor(255, 255, 255)

FONT_TITLE = "Calibri"
FONT_BODY  = "Calibri"
FONT_SANS  = "Calibri"

LOGO_PATH = "assets/alliance_logo_clean.png"

def create_presentation():
    prs = pptx.Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT
    blank_layout = prs.slide_layouts[6]
    return prs, blank_layout

def add_header(slide, title_text, is_title_slide=False):
    """Adds the official Alliance University logo and centered title matching friend's deck."""
    if os.path.exists(LOGO_PATH):
        slide.shapes.add_picture(LOGO_PATH, Inches(9.50), Inches(0.32), Inches(3.45), Inches(0.65))
    
    if not is_title_slide and title_text:
        tb = slide.shapes.add_textbox(Inches(1.0), Inches(0.40), Inches(11.333), Inches(0.9))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        p.text = title_text
        p.font.name = FONT_TITLE
        p.font.size = Pt(40)
        p.font.bold = True
        p.font.color.rgb = SLATE_DARK

def add_bullet_points(slide, left, top, width, height, bullets, font_size=23, space_after=14):
    """Adds large, projector-optimized bullet points matching friend's slides."""
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    
    for i, b_text in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        p.line_spacing = 1.18
        
        # Bullet character
        run_bullet = p.add_run()
        run_bullet.text = "•  "
        run_bullet.font.name = "Arial"
        run_bullet.font.size = Pt(font_size)
        run_bullet.font.bold = True
        run_bullet.font.color.rgb = NAVY_PRIMARY
        
        # Text body
        run_text = p.add_run()
        run_text.text = b_text
        run_text.font.name = FONT_BODY
        run_text.font.size = Pt(font_size)
        run_text.font.color.rgb = SLATE_DARK

def create_table(slide, left, top, width, height, col_widths, headers, rows_data, header_size=11, row_size=9.5):
    """Creates a table matching the friend's LITERATURE REVIEW TABLE styling."""
    num_rows = len(rows_data) + 1
    num_cols = len(headers)
    table_shape = slide.shapes.add_table(num_rows, num_cols, left, top, width, height)
    table = table_shape.table
    
    for col_idx, col_w in enumerate(col_widths):
        table.columns[col_idx].width = col_w
    
    for col_idx, h_text in enumerate(headers):
        cell = table.cell(0, col_idx)
        cell.fill.solid()
        cell.fill.fore_color.rgb = BLUE_HEADER
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.08)
        cell.margin_top = cell.margin_bottom = Inches(0.05)
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER if col_idx == 0 else PP_ALIGN.LEFT
        p.text = h_text
        p.font.name = FONT_SANS
        p.font.size = Pt(header_size)
        p.font.bold = True
        p.font.color.rgb = HEADER_TEXT
        
    for row_idx, row_values in enumerate(rows_data):
        row_num = row_idx + 1
        bg = ROW_ALT_BG if row_idx % 2 == 1 else WHITE
        for col_idx, val in enumerate(row_values):
            cell = table.cell(row_num, col_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if col_idx == 0 else PP_ALIGN.LEFT
            p.text = str(val)
            p.font.name = FONT_BODY
            p.font.size = Pt(row_size)
            p.font.color.rgb = SLATE_DARK
            if col_idx == 0:
                p.font.bold = True
                p.font.name = FONT_SANS
                p.font.color.rgb = NAVY_PRIMARY

# ==============================================================================
# SLIDE BUILDERS (EXACTLY 11 SLIDES MATCHING FRIEND'S PRESENTATION)
# ==============================================================================

def build_slide_1(prs, layout):
    """Slide 1: Title of the Project"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "", is_title_slide=True)
    
    # Title box (matching friend's top title styling)
    tb_title = slide.shapes.add_textbox(Inches(0.8), Inches(1.3), Inches(11.7), Inches(1.6))
    tf_title = tb_title.text_frame
    tf_title.word_wrap = True
    
    p_title = tf_title.paragraphs[0]
    p_title.text = "Context-Aware Smart LLM Switching for Cost and Performance Optimization"
    p_title.font.name = FONT_TITLE
    p_title.font.size = Pt(36)
    p_title.font.bold = True
    p_title.font.color.rgb = SLATE_DARK
    p_title.space_after = Pt(24)

    # Team Members Block
    tb_team = slide.shapes.add_textbox(Inches(0.8), Inches(3.2), Inches(11.7), Inches(2.2))
    tf_team = tb_team.text_frame
    tf_team.word_wrap = True
    
    p_tm = tf_team.paragraphs[0]
    p_tm.text = "Team Members:"
    p_tm.font.name = FONT_TITLE
    p_tm.font.size = Pt(22)
    p_tm.font.bold = True
    p_tm.font.color.rgb = SLATE_DARK
    p_tm.space_after = Pt(8)
    
    members = [
        "1. NEVIN TONY - 2411021061276",
        "2. TEKUMUDI RAMA KRISHNA - 2411021061402",
        "3. SHAIK.MUHEEB AHAMAD BASHA - 2411021061091",
        "4. GAALI VAMSI KRISHNA - 2411021061062",
    ]
    for m in members:
        p = tf_team.add_paragraph()
        p.space_after = Pt(5)
        p.text = m
        p.font.name = FONT_TITLE
        p.font.size = Pt(20)
        p.font.color.rgb = SLATE_DARK

    # Mentor details & Course code (bottom)
    tb_foot = slide.shapes.add_textbox(Inches(0.8), Inches(5.7), Inches(11.7), Inches(1.3))
    tf_foot = tb_foot.text_frame
    tf_foot.word_wrap = True
    
    p_men = tf_foot.paragraphs[0]
    p_men.text = "Name of the Mentor: ____________________________________"
    p_men.font.name = FONT_TITLE
    p_men.font.size = Pt(22)
    p_men.font.color.rgb = SLATE_DARK
    p_men.space_after = Pt(12)
    
    p_course = tf_foot.add_paragraph()
    p_course.text = "E1CSA313/E1ITA306 Design Project -1"
    p_course.font.name = "Bookman Old Style"
    p_course.font.size = Pt(28)
    p_course.font.color.rgb = SLATE_DARK

def build_slide_2(prs, layout):
    """Slide 2: INDEX TABLE"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "INDEX TABLE")
    
    # Table dimensions and placement matching friend's slide 2
    col_widths = [Inches(4.5), Inches(6.5)]
    headers = ["S.No", "Contents"]
    rows = [
        ["1.", "Title of the Project"],
        ["2.", "Introduction"],
        ["3.", "Overall Diagram"],
        ["4.", "Literature Review"],
        ["5.", "Gap Analysis / Overall Gap in Existing Technology"],
        ["6.", "Conclusion"],
        ["7.", "References"]
    ]
    
    table_shape = slide.shapes.add_table(8, 2, Inches(1.2), Inches(1.7), Inches(11.0), Inches(5.1))
    table = table_shape.table
    table.columns[0].width = col_widths[0]
    table.columns[1].width = col_widths[1]
    
    # Headers
    for c_idx, h_text in enumerate(headers):
        cell = table.cell(0, c_idx)
        cell.fill.solid()
        cell.fill.fore_color.rgb = BLUE_HEADER
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER if c_idx == 0 else PP_ALIGN.LEFT
        p.text = h_text
        p.font.name = FONT_TITLE
        p.font.size = Pt(20)
        p.font.bold = True
        p.font.color.rgb = HEADER_TEXT
        
    # Rows
    for r_idx, (sno, content) in enumerate(rows):
        bg = ROW_ALT_BG if r_idx % 2 == 1 else WHITE
        cell0 = table.cell(r_idx + 1, 0)
        cell1 = table.cell(r_idx + 1, 1)
        
        cell0.fill.solid()
        cell0.fill.fore_color.rgb = bg
        cell0.vertical_anchor = MSO_ANCHOR.MIDDLE
        p0 = cell0.text_frame.paragraphs[0]
        p0.alignment = PP_ALIGN.CENTER
        p0.text = sno
        p0.font.name = FONT_TITLE
        p0.font.size = Pt(18)
        p0.font.bold = True
        p0.font.color.rgb = SLATE_DARK
        
        cell1.fill.solid()
        cell1.fill.fore_color.rgb = bg
        cell1.vertical_anchor = MSO_ANCHOR.MIDDLE
        p1 = cell1.text_frame.paragraphs[0]
        p1.text = content
        p1.font.name = FONT_TITLE
        p1.font.size = Pt(18)
        p1.font.bold = True
        p1.font.color.rgb = SLATE_DARK

def build_slide_3(prs, layout):
    """Slide 3: INTRODUCTION"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "INTRODUCTION")
    
    bullets = [
        "High inference cost is a major hurdle in AI applications, especially when calling premium models.",
        "Most LLM systems route every incoming user query to a single heavy, expensive model.",
        "Our project focuses on intelligently switching between models before generating the answer.",
        "We use a lightweight Analyzer LLM as an early decision signal for task difficulty and context.",
        "Simple queries are answered directly by the analyzer itself, saving unnecessary downstream calls.",
        "Complex coding and reasoning tasks are switched to the most capable model for maximum accuracy.",
        "The real-time token usage, latency, and cost savings are displayed using an interactive dashboard."
    ]
    add_bullet_points(slide, Inches(1.0), Inches(1.6), Inches(11.333), Inches(5.3), bullets, font_size=23, space_after=13)

def build_slide_4(prs, layout):
    """Slide 4: DIAGRAM (Overall System Diagram - Matching Friend's 7-Stage Flowchart)"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "DIAGRAM")
    
    # Hero Title Banner (matching friend's blue banner)
    banner = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(3.8), Inches(1.5), Inches(5.7), Inches(0.55))
    banner.fill.solid()
    banner.fill.fore_color.rgb = RGBColor(189, 215, 238)
    banner.line.color.rgb = BLUE_HEADER
    p_b = banner.text_frame.paragraphs[0]
    p_b.alignment = PP_ALIGN.CENTER
    p_b.text = "Overall System Diagram"
    p_b.font.name = FONT_TITLE
    p_b.font.size = Pt(22)
    p_b.font.bold = True
    p_b.font.color.rgb = SLATE_DARK

    # 7 Stage Pipeline Cards (horizontal flow matching friend's 7 stages)
    stages = [
        {
            "title": "User Query\nInput",
            "items": ["User prompt", "Chat history", "Strategy mode"]
        },
        {
            "title": "Request\nGuardrails",
            "items": ["FastAPI gateway", "Token context trim", "Budget caps"]
        },
        {
            "title": "Semantic\nRouting Cache",
            "items": ["SHA-1 query digest", "Fast cache hit", "<15ms response"]
        },
        {
            "title": "Dual-Role\nAnalyzer LLM",
            "items": ["Task complexity", "Self-Mode (1 call)", "Switch-Mode signal"]
        },
        {
            "title": "Smart Routing\n(7-Factor)",
            "items": ["Quality & latency", "Cost efficiency", "Coding / reasoning"]
        },
        {
            "title": "Resilient Model\nExecution",
            "items": ["Gemini / Groq / OpenAI", "Circuit breaker", "Automated fallback"]
        },
        {
            "title": "Output\n(Dashboard)",
            "items": ["Real-time SSE", "Token & cost audit", "Savings inspector"]
        }
    ]
    
    card_w = Inches(1.54)
    card_h = Inches(3.4)
    start_x = Inches(0.6)
    gap = Inches(0.18)
    y_pos = Inches(2.3)
    
    for idx, stg in enumerate(stages):
        x = start_x + idx * (card_w + gap)
        
        # Main box
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y_pos, card_w, card_h)
        box.fill.solid()
        box.fill.fore_color.rgb = WHITE
        box.line.color.rgb = CARD_BORDER
        box.line.width = Pt(1)
        
        # Header banner inside box
        hdr = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y_pos, card_w, Inches(0.85))
        hdr.fill.solid()
        hdr.fill.fore_color.rgb = STAGE_BG
        hdr.line.color.rgb = BLUE_HEADER
        hdr.line.width = Pt(1)
        
        tf_h = hdr.text_frame
        tf_h.word_wrap = True
        tf_h.margin_left = tf_h.margin_right = tf_h.margin_top = tf_h.margin_bottom = 0
        p_h = tf_h.paragraphs[0]
        p_h.alignment = PP_ALIGN.CENTER
        p_h.text = stg["title"]
        p_h.font.name = FONT_TITLE
        p_h.font.size = Pt(12)
        p_h.font.bold = True
        p_h.font.color.rgb = SLATE_DARK
        
        # Content bullets inside box
        tb_body = slide.shapes.add_textbox(x, y_pos + Inches(0.95), card_w, Inches(2.3))
        tf_b = tb_body.text_frame
        tf_b.word_wrap = True
        tf_b.margin_left = tf_b.margin_right = Inches(0.06)
        tf_b.margin_top = Inches(0.04)
        
        for b_idx, item in enumerate(stg["items"]):
            p = tf_b.paragraphs[0] if b_idx == 0 else tf_b.add_paragraph()
            p.space_after = Pt(4)
            p.text = "• " + item
            p.font.name = FONT_TITLE
            p.font.size = Pt(10)
            p.font.color.rgb = SLATE_DARK
            
        # Arrow between cards
        if idx < len(stages) - 1:
            arr_x = x + card_w + Inches(0.02)
            arr = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, arr_x, y_pos + Inches(1.5), Inches(0.14), Inches(0.18))
            arr.fill.solid()
            arr.fill.fore_color.rgb = BLUE_HEADER
            arr.line.color.rgb = BLUE_HEADER

    # Continuous Monitoring Feedback loop at the bottom (matching friend's dotted line)
    loop_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(3.6), Inches(6.1), Inches(6.1), Inches(0.5))
    loop_box.fill.solid()
    loop_box.fill.fore_color.rgb = WHITE
    loop_box.line.color.rgb = SLATE_DARK
    loop_box.line.width = Pt(1)
    p_l = loop_box.text_frame.paragraphs[0]
    p_l.alignment = PP_ALIGN.CENTER
    p_l.text = "Continuous Monitoring & Circuit Health Update"
    p_l.font.name = FONT_TITLE
    p_l.font.size = Pt(13)
    p_l.font.bold = True
    p_l.font.color.rgb = SLATE_DARK

def build_slide_5(prs, layout):
    """Slide 5: LITERATURE REVIEW TABLE (Papers 1 to 5)"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "LITERATURE REVIEW TABLE")
    
    col_widths = [Inches(0.6), Inches(2.4), Inches(2.7), Inches(1.8), Inches(2.1), Inches(2.13)]
    headers = [
        "S.No",
        "Author Name, Paper Title,\nJournal / Year",
        "Research / Methodology / Dataset",
        "Performance Metrics / Results",
        "Advantages / Relevance to\nProposed Project",
        "Disadvantages / Limitations"
    ]
    rows = [
        [
            "1",
            "Lingjiao Chen, Matei Zaharia,\nJames Zou\nFrugalGPT\nStanford, 2023",
            "Model cascading with score-based completion stopping across multiple cloud LLMs.",
            "Cost reduction up to 98%; matched individual performance of GPT-4 on benchmarks.",
            "Proves multi-model cascading reduces expense; directly inspires our smart switching.",
            "Sequential cascade causes compounding latency; cannot self-answer simple queries."
        ],
        [
            "2",
            "Isaac Ong, Amjad Almahairi et al.\nRouteLLM: Learning to Route\nLLMs with Preference Data\nLMSYS / UC Berkeley, 2024",
            "Router trained on Chatbot Arena human preference data with matrix factorization & embeddings.",
            "Reduces cost by 50% while matching 95% GPT-4 quality; latency ~180ms.",
            "Validates that compact routers make accurate routing choices on user preferences.",
            "Limited to binary choices (2 models); no multi-provider fallback or budget caps."
        ],
        [
            "3",
            "Yaniv Leviathan, Matan Kalman,\nYossi Matias\nSpeculative Decoding\nGoogle Research, ICML 2023",
            "Small draft model proposes candidate tokens verified by large target LLM in parallel.",
            "2x to 3x wall-clock latency speedup with mathematically identical token distribution.",
            "Maintains 100% output fidelity while speeding up inference response.",
            "Requires co-located GPU memory; cannot route across independent cloud APIs."
        ],
        [
            "4",
            "Tal Shnitzer et al.\nLarge Language Model Routing\nwith Benchmark Datasets\nNeurIPS ENLSP, 2023",
            "Classification-based router matching queries to specialized models using task embeddings.",
            "32% higher accuracy on GSM8K and HumanEval over standalone uniform models.",
            "Demonstrates that model specialization produces superior domain answers.",
            "High embedding overhead; static classifier requires retraining on new models."
        ],
        [
            "5",
            "Kai Mei, Wujiang Xu et al.\nRouting to Diverse Language\nModels via Multi-Task Predictors\nIEEE TKDE, 2024",
            "Multi-task performance predictors estimating accuracy and latency vectors across LLMs.",
            "41% latency reduction and 62% cost savings across MMLU, ARC, and TriviaQA.",
            "Provides an explicit Pareto frontier between quality, cost, and latency.",
            "Trained on static benchmark questions; lacks real multi-turn conversation support."
        ]
    ]
    create_table(slide, Inches(0.8), Inches(1.6), Inches(11.73), Inches(5.3), col_widths, headers, rows, header_size=10.5, row_size=9.2)

def build_slide_6(prs, layout):
    """Slide 6: LITERATURE REVIEW TABLE (Papers 6 to 10)"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "LITERATURE REVIEW TABLE")
    
    col_widths = [Inches(0.6), Inches(2.4), Inches(2.7), Inches(1.8), Inches(2.1), Inches(2.13)]
    headers = [
        "S.No",
        "Author Name, Paper Title,\nJournal / Year",
        "Research / Methodology / Dataset",
        "Performance Metrics / Results",
        "Advantages / Relevance to\nProposed Project",
        "Disadvantages / Limitations"
    ]
    rows = [
        [
            "6",
            "Junlin Wang, Jue Wang et al.\nMixture-of-Agents Enhances\nLLM Capabilities\nTogether AI, 2024",
            "Layered multi-agent architecture where multiple open-weight LLMs synthesize outputs.",
            "65.1% AlpacaEval 2.0 win rate, surpassing standalone GPT-4 Omni.",
            "Shows that ensembling diverse model outputs produces strong reasoning quality.",
            "Consumes Nx multiple tokens and high latency; unaffordable for cost-sensitive tasks."
        ],
        [
            "7",
            "Albert Q. Jiang et al.\nMixtral of Experts\nMistral AI Research, 2024",
            "Sparse Mixture of Experts router selecting top-2 feed-forward expert networks per token.",
            "Matches GPT-3.5 quality with 12.9B active parameters; 6x faster inference.",
            "Demonstrates token-level routing efficiency within a single weight architecture.",
            "Internal router cannot dynamically switch between third-party cloud APIs."
        ],
        [
            "8",
            "Xupeng Miao et al.\nSpecInfer: Accelerating Generative\nLLM Serving\nACM ASPLOS, 2024",
            "Tree-based speculative inference using multiple small draft models to verify candidate trees.",
            "2.6x to 3.5x serving throughput increase on distributed GPU clusters.",
            "Saves GPU memory bandwidth and scales serving throughput efficiently.",
            "Requires low-level CUDA integration; inapplicable to closed cloud APIs."
        ],
        [
            "9",
            "Dongfu Jiang, Xiang Ren, Bill Yuchen Lin\nLLM-Blender: Ensembling Models\nwith Pairwise Ranking\nACL Findings, 2023",
            "PairRanker module scores candidate answers followed by GenFuser generative synthesis.",
            "8.9% higher BLEURT and human preference over individual best model responses.",
            "Effectively ensembles candidate responses to resolve prompt ambiguity.",
            "Runs all candidate models simultaneously, creating huge redundant API costs."
        ],
        [
            "10",
            "Boyuan Chen, Siddharth Garg et al.\nCost-Effective Model Cascading\nfor Query Answering\nPVLDB Vol. 17, 2024",
            "Confidence-calibrated cascade thresholding assessing query difficulty before dispatch.",
            "58% inference cost reduction on enterprise QA workloads with <1.5% accuracy drop.",
            "Rigorous mathematical formulation for difficulty assessment and dispatch.",
            "Lacks provider circuit breakers, fallback chains, and context budgeting."
        ]
    ]
    create_table(slide, Inches(0.8), Inches(1.6), Inches(11.73), Inches(5.3), col_widths, headers, rows, header_size=10.5, row_size=9.2)

def build_slide_7(prs, layout):
    """Slide 7: GAP ANALYSIS (Part 1)"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "GAP ANALYSIS")
    
    bullets = [
        "Existing LLM deployment architectures treat all user queries equally, sending basic questions to expensive models.",
        "Most current routers function solely as passive dispatchers, always calling an external model rather than answering simple queries directly.",
        "Traditional sequential cascading models test small models first and escalate on failure, causing compounding latency delays on difficult tasks.",
        "Many existing routing systems only support binary choices (cheap vs. expensive), ignoring multi-tier options like dedicated coding or ultra-fast models.",
        "Cloud provider disruptions such as rate limits (HTTP 429) and network timeouts are rarely addressed in existing routing frameworks."
    ]
    add_bullet_points(slide, Inches(1.0), Inches(1.6), Inches(11.333), Inches(5.3), bullets, font_size=23, space_after=14)

def build_slide_8(prs, layout):
    """Slide 8: GAP ANALYSIS (Part 2 - Overall Gap in Existing Technology)"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "GAP ANALYSIS")
    
    bullets = [
        "There is a gap in combining proactive self-answering, multi-factor model selection, provider circuit breaking, and honest token tracking into a single unified system.",
        "Our project attempts to fill this gap by creating an adaptive, context-aware switching framework that answers routine queries in a single pass, intelligently switches complex tasks to specialized models, and maintains continuous availability with automatic fallback."
    ]
    add_bullet_points(slide, Inches(1.0), Inches(2.2), Inches(11.333), Inches(4.5), bullets, font_size=25, space_after=24)

def build_slide_9(prs, layout):
    """Slide 9: CONCLUSION"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "CONCLUSION")
    
    bullets = [
        "Our project presents a proactive approach to LLM serving by using a fast Analyzer LLM and the context of the conversation to identify query difficulty in advance and route to the most suitable model.",
        "It resolves simple queries directly in one call to save costs, while dynamically routing complex coding and reasoning prompts to top-performing models, delivering results through a simple dashboard that helps move from blind model calling to intelligent, cost-optimized switching."
    ]
    add_bullet_points(slide, Inches(1.0), Inches(2.1), Inches(11.333), Inches(4.6), bullets, font_size=25, space_after=22)

def build_slide_10(prs, layout):
    """Slide 10: REFERENCES (Papers 1 to 6)"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "REFERENCES")
    
    refs = [
        "Lingjiao Chen, Matei Zaharia, James Zou, “FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance,” arXiv preprint arXiv:2305.05176, 2023.",
        "Isaac Ong, Amjad Almahairi, et al., “RouteLLM: Learning to Route LLMs with Preference Data,” LMSYS Org, arXiv preprint arXiv:2406.18665, 2024.",
        "Yaniv Leviathan, Matan Kalman, Yossi Matias, “Fast Inference from Transformers via Speculative Decoding,” International Conference on Machine Learning (ICML), PMLR 202:19274-19286, 2023.",
        "Tal Shnitzer, et al., “Large Language Model Routing with Benchmark Datasets,” NeurIPS Workshop on Efficient Natural Language and Speech Processing (ENLSP), 2023.",
        "Kai Mei, Wujiang Xu, Yongfeng Zhang, et al., “Routing to Diverse Language Models via Multi-Task Performance Predictors,” IEEE Transactions on Knowledge and Data Engineering (TKDE), 2024.",
        "Junlin Wang, Jue Wang, et al., “Mixture-of-Agents Enhances Large Language Model Capabilities,” Together AI Research, arXiv preprint arXiv:2406.04692, 2024."
    ]
    add_bullet_points(slide, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.5), refs, font_size=18, space_after=10)

def build_slide_11(prs, layout):
    """Slide 11: REFERENCES (Papers 7 to 10)"""
    slide = prs.slides.add_slide(layout)
    add_header(slide, "REFERENCES")
    
    refs = [
        "Albert Q. Jiang, et al., “Mixtral of Experts,” Mistral AI Research, arXiv preprint arXiv:2401.04088, 2024.",
        "Xupeng Miao, et al., “SpecInfer: Accelerating Generative LLM Serving with Tree-based Speculative Inference and Verification,” ACM ASPLOS, 2024.",
        "Dongfu Jiang, Xiang Ren, Bill Yuchen Lin, “LLM-Blender: Ensembling Large Language Models with Pairwise Ranking and Generative Fusion,” Findings of the ACL, pp. 8045-8065, 2023.",
        "Boyuan Chen, Mingzhi Zhu, Siddharth Garg, et al., “Cost-Effective Model Cascading for Query Answering,” Proceedings of the VLDB Endowment (PVLDB), Vol. 17, No. 6, 2024."
    ]
    add_bullet_points(slide, Inches(0.8), Inches(1.8), Inches(11.7), Inches(5.0), refs, font_size=20, space_after=16)

# ==============================================================================
# MAIN ROUTINE
# ==============================================================================

def main():
    prs, layout = create_presentation()
    
    print("Building Slide 1: Title of the Project...")
    build_slide_1(prs, layout)
    
    print("Building Slide 2: INDEX TABLE...")
    build_slide_2(prs, layout)
    
    print("Building Slide 3: INTRODUCTION...")
    build_slide_3(prs, layout)
    
    print("Building Slide 4: DIAGRAM (Overall System Diagram)...")
    build_slide_4(prs, layout)
    
    print("Building Slide 5: LITERATURE REVIEW TABLE (Part 1)...")
    build_slide_5(prs, layout)
    
    print("Building Slide 6: LITERATURE REVIEW TABLE (Part 2)...")
    build_slide_6(prs, layout)
    
    print("Building Slide 7: GAP ANALYSIS (Part 1)...")
    build_slide_7(prs, layout)
    
    print("Building Slide 8: GAP ANALYSIS (Part 2)...")
    build_slide_8(prs, layout)
    
    print("Building Slide 9: CONCLUSION...")
    build_slide_9(prs, layout)
    
    print("Building Slide 10: REFERENCES (Part 1)...")
    build_slide_10(prs, layout)
    
    print("Building Slide 11: REFERENCES (Part 2)...")
    build_slide_11(prs, layout)
    
    target_filename = "Design Project Context of Smart llm switching for Cost and Performance Optimization.pptx"
    desktop_path = os.path.join(r"C:\Users\rama krishna\OneDrive\Desktop", target_filename)
    workspace_path = os.path.join(os.getcwd(), target_filename)
    
    print(f"Saving presentation to Desktop: {desktop_path} ...")
    prs.save(desktop_path)
    
    print(f"Saving copy to Workspace: {workspace_path} ...")
    prs.save(workspace_path)
    
    print("SUCCESS: 11-Slide Streamlined Presentation Created Successfully!")

if __name__ == "__main__":
    main()
