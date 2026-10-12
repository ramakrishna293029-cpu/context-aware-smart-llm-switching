"""
Generates high-resolution methodology diagram for the Design Project Report.
Saves to assets/methodology_diagram.png and report/methodology_diagram.png.
"""

import os
import matplotlib.pyplot as plt
import matplotlib.patches as patches

def draw_methodology_diagram(output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Create figure with high DPI
    fig, ax = plt.subplots(figsize=(12, 6.2), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 52)
    ax.axis('off')
    
    # Background fill
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')

    # Color Palette
    navy = '#0F2C59'
    blue = '#2E75B6'
    blue_header = '#1F4E79'
    green = '#107C41'
    amber = '#C55A11'
    slate_dark = '#262626'
    slate_muted = '#595959'
    card_border = '#BDD7EE'
    card_bg = '#F2F7FC'
    card_green_bg = '#EBF7EE'
    card_amber_bg = '#FEF5EA'
    
    # Helper to draw rounded box
    def draw_box(x, y, w, h, title, items, fill_color, border_color, title_color=navy, title_size=10, item_size=8.2, badge=None):
        rect = patches.FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.5,rounding_size=1.2",
            facecolor=fill_color, edgecolor=border_color, linewidth=1.4
        )
        ax.add_patch(rect)
        
        # Title
        ax.text(x + w/2, y + h - 2.8, title, ha='center', va='center',
                fontsize=title_size, fontweight='bold', color=title_color, family='sans-serif')
        
        if badge:
            badge_rect = patches.FancyBboxPatch(
                (x + w - 16, y + h - 3.8), 15, 2.4,
                boxstyle="round,pad=0.2,rounding_size=0.6",
                facecolor=border_color, edgecolor=border_color
            )
            ax.add_patch(badge_rect)
            ax.text(x + w - 8.5, y + h - 2.6, badge, ha='center', va='center',
                    fontsize=7, fontweight='bold', color='#FFFFFF', family='sans-serif')
        
        # Items
        curr_y = y + h - 5.5
        for item in items:
            ax.text(x + 1.8, curr_y, item, ha='left', va='center',
                    fontsize=item_size, color=slate_dark, family='sans-serif')
            curr_y -= 2.6

    # Helper to draw arrow
    def draw_arrow(x1, y1, x2, y2, color=blue, text="", text_y_offset=1.2, text_color=blue):
        ax.annotate(
            '', xy=(x2, y2), xytext=(x1, y1),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8, mutation_scale=14)
        )
        if text:
            ax.text((x1 + x2)/2, (y1 + y2)/2 + text_y_offset, text, ha='center', va='center',
                    fontsize=8.5, fontweight='bold', color=text_color, family='sans-serif')

    # Title Bar
    title_rect = patches.FancyBboxPatch(
        (2, 47), 96, 4.2,
        boxstyle="round,pad=0.3,rounding_size=0.8",
        facecolor=navy, edgecolor=navy
    )
    ax.add_patch(title_rect)
    ax.text(50, 49.1, "END-TO-END METHODOLOGY & ARCHITECTURAL DATAFLOW",
            ha='center', va='center', fontsize=11.5, fontweight='bold', color='#FFFFFF', family='sans-serif')

    # Stage 1: Ingestion & Pre-Flight (Left)
    draw_box(
        2, 27.5, 20, 17.5,
        "1. Ingestion & Pre-Flight",
        ["• Inbound User Query & Context",
         "• Token Trimmer (MAX_TOKENS)",
         "• Spend Caps ($ Daily / Monthly)",
         "• Strategy Selector (4 Profiles)",
         "• FastAPI Async Engine"],
        card_bg, card_border, badge="PHASE I"
    )

    # Arrow 1 -> Cache
    draw_arrow(22.8, 36.2, 27.8, 36.2, blue, "Prompt")

    # Stage 2: Cache & Analyzer
    draw_box(
        28, 27.5, 21, 17.5,
        "2. Cache & Analyzer Brain",
        ["• SHA-1 Semantic Cache (<15ms)",
         "• Analyzer LLM (Cheapest Tier)",
         "• Strict JSON Contract Parsing",
         "• Complexity Scored [0.0 - 1.0]",
         "• Coding & Reasoning Detection"],
        card_bg, card_border, badge="PHASE II"
    )

    # Cache hit short-circuit line
    ax.annotate(
        '', xy=(12, 27.2), xytext=(38.5, 27.2),
        arrowprops=dict(arrowstyle="->", color=amber, lw=1.3, ls="--", mutation_scale=12)
    )
    ax.text(25.5, 25.8, "Cache Hit (<15ms Instant Return)", ha='center', va='center',
            fontsize=7.5, fontweight='bold', color=amber, family='sans-serif')

    # Arrow 2 -> Branch A (Self-Mode)
    draw_arrow(49.5, 40.5, 54.5, 40.5, green, "Self (Simple)", 1.2, green)

    # Arrow 2 -> Branch B (Switch-Mode)
    draw_arrow(49.5, 32.0, 54.5, 32.0, blue, "Switch (Complex)", 1.2, blue)

    # Branch A: Self-Mode (Single-Pass)
    draw_box(
        55, 35.8, 43, 9.2,
        "BRANCH A: Single-Pass Self-Mode Resolution (Fast & Cost-Optimal)",
        ["• Analyzer LLM answers immediately in the initial triage pass (answer_mode = 'self')",
         "• 0 Downstream model tokens dispatched; 91.3% - 93.2% measured cost savings",
         "• Ideal for greetings, definitions, syntax lookups, and basic multi-turn queries"],
        card_green_bg, green, title_color=green, badge="SELF-MODE"
    )

    # Branch B: Switch-Mode (Multi-Factor Scoring)
    draw_box(
        55, 24.5, 43, 10.0,
        "BRANCH B: 7-Factor Capability Scoring & Tier Resolution",
        ["• Multi-Criteria Scoring: S = Quality + Complexity + Reason + Code + Cost + Latency + Hist",
         "• Dynamic Weighting Matrices based on strategy (Balanced, Cost, Speed, Quality)",
         "• Targets: Specialized Coding (Groq Qwen/Llama-70B), Reasoning, or Frontier tiers"],
        card_bg, blue, title_color=blue, badge="SWITCH-MODE"
    )

    # Arrow from Branch B down to Stage 3
    draw_arrow(76.5, 24.2, 76.5, 19.8, blue)

    # Stage 3: Circuit Breaker & Fallback Chain
    draw_box(
        35, 9.5, 63, 10.0,
        "3. Provider Circuit Breaker & Resilient Model Execution Chain",
        ["• ProviderCircuit Health Gate: Tracks consecutive failures (Threshold = 2, Cooldown = 30s)",
         "• Fallback Cascade: Primary Failure (HTTP 429 / Timeout) -> Instant auto-failover to 2nd-best model",
         "• Unified Multi-Provider Adapters: OpenAI (4o/mini), Groq (Llama-3.3/Qwen), Gemini, OpenRouter, vLLM",
         "• Real-Time Token Streaming via Server-Sent Events (SSE) with Time-To-First-Token (TTFT) clock"],
        card_amber_bg, amber, title_color=amber, badge="RESILIENCE"
    )

    # Arrow from Branch A down to Persistence & Streaming
    ax.annotate(
        '', xy=(24.5, 12.0), xytext=(54.8, 38.0),
        arrowprops=dict(arrowstyle="->", color=green, lw=1.5, ls="-.", mutation_scale=12)
    )

    # Arrow from Stage 3 to Stage 4 (Telemetry & UI)
    draw_arrow(34.8, 14.5, 25.5, 14.5, navy)

    # Stage 4: Telemetry Persistence & Dashboard
    draw_box(
        2, 2.5, 23, 17.5,
        "4. Telemetry & Audit",
        ["• 100% Provider Usage Logged",
         "• Dual-Call Latency Accounting",
         "• SQLite WAL Database (metrics.db)",
         "• Request Inspector Audit Trail",
         "• Zero Fabricated Token Estimates",
         "• Real-Time Dashboard Rollup"],
        card_bg, card_border, badge="PHASE IV"
    )

    # Output Delivery Box
    draw_box(
        35, 1.8, 63, 6.8,
        "Final User Delivery: Low Latency, High Reasoning, 70.94% Lower Cost",
        ["• Clean Markdown & KaTeX rendering; zero downtime through automated fault isolation",
         "• Verified benchmark: 70.94% mean cost reduction, 2,122 ms latency, 100% request success rate"],
        '#FFFFFF', navy, title_color=navy, badge="OUTCOME"
    )

    # Arrow from stage 3 to stage 5
    draw_arrow(66.5, 9.2, 66.5, 8.8, navy)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Diagram successfully saved to: {output_path}")

if __name__ == "__main__":
    desktop_report = r"C:\Users\rama krishna\OneDrive\Desktop\report"
    os.makedirs(desktop_report, exist_ok=True)
    draw_methodology_diagram(os.path.join(desktop_report, "methodology_diagram.png"))
    
    # Also save in local assets for reference
    os.makedirs("assets", exist_ok=True)
    draw_methodology_diagram("assets/methodology_diagram.png")
