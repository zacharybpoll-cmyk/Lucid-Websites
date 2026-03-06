"""
Voice Wellness Report — PDF generation using ReportLab.
Generates a clinical-style PDF with stress trends, zone breakdowns, and insights.
"""
import io
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.graphics.shapes import Drawing, Line, String, Rect
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics import renderPDF

logger = logging.getLogger('lucid.report')

# Brand colors
STEEL_BLUE = colors.HexColor('#5B8DB8')
DARK_TEXT = colors.HexColor('#1a1d21')
BODY_TEXT = colors.HexColor('#5a6270')
LIGHT_BG = colors.HexColor('#f8f9fa')
BORDER_GRAY = colors.HexColor('#e4e8ec')


class WellnessReportGenerator:
    """Generates Voice Wellness PDF reports."""

    def __init__(self, db):
        self.db = db

    def generate(self, days: int = 90, user_name: str = "User") -> bytes:
        """Generate a PDF report and return as bytes.

        Args:
            days: Number of days to cover
            user_name: Name to display on cover page

        Returns:
            PDF file contents as bytes
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=60,
            leftMargin=60,
            topMargin=60,
            bottomMargin=60,
        )

        styles = getSampleStyleSheet()
        # Custom styles
        styles.add(ParagraphStyle(
            'CoverTitle',
            parent=styles['Title'],
            fontName='Times-Roman',
            fontSize=28,
            textColor=DARK_TEXT,
            spaceAfter=8,
        ))
        styles.add(ParagraphStyle(
            'CoverSubtitle',
            parent=styles['Normal'],
            fontSize=14,
            textColor=BODY_TEXT,
            spaceAfter=24,
        ))
        styles.add(ParagraphStyle(
            'SectionHead',
            parent=styles['Heading2'],
            fontName='Times-Roman',
            fontSize=16,
            textColor=DARK_TEXT,
            spaceBefore=20,
            spaceAfter=12,
        ))
        styles.add(ParagraphStyle(
            'BodyText2',
            parent=styles['Normal'],
            fontSize=10,
            textColor=BODY_TEXT,
            spaceAfter=8,
        ))
        styles.add(ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=BODY_TEXT,
            alignment=1,  # Center
        ))

        # Gather data
        summaries = self.db.get_daily_summaries(days=days)
        summaries = sorted(summaries, key=lambda s: s['date'])

        elements = []

        # ===== Cover Page =====
        elements.append(Spacer(1, 120))
        elements.append(Paragraph("Clinical Voice Wellness Report", styles['CoverTitle']))

        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        date_range = f"{days}-Day Clinical Summary — {end_date.strftime('%B %Y')}"
        elements.append(Paragraph(date_range, styles['CoverSubtitle']))

        # Horizontal rule
        d = Drawing(480, 2)
        d.add(Line(0, 1, 480, 1, strokeColor=STEEL_BLUE, strokeWidth=2))
        elements.append(d)
        elements.append(Spacer(1, 24))

        elements.append(Paragraph(f"Patient: {user_name}", styles['BodyText2']))
        elements.append(Paragraph("Prepared by: Lucid Voice Monitor", styles['BodyText2']))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['BodyText2']))
        elements.append(Spacer(1, 40))
        elements.append(Paragraph(
            "This report summarizes voice-derived wellness indicators over the specified period. "
            "Data is extracted from passive voice pattern analysis and should be reviewed in "
            "conjunction with clinical assessment.",
            styles['BodyText2']
        ))

        elements.append(PageBreak())

        # ===== Page 2: Stress Trend =====
        elements.append(Paragraph("Stress Index Trend", styles['SectionHead']))

        if summaries:
            chart = self._build_stress_chart(summaries)
            elements.append(chart)
            elements.append(Spacer(1, 12))

            # Summary stats
            stress_values = [s.get('avg_stress', 50) or 50 for s in summaries]
            avg_stress = sum(stress_values) / len(stress_values)
            min_stress = min(stress_values)
            max_stress = max(stress_values)

            stats_data = [
                ['Metric', 'Value'],
                ['Average Stress', f'{avg_stress:.1f}'],
                ['Lowest Stress', f'{min_stress:.1f}'],
                ['Highest Stress', f'{max_stress:.1f}'],
                ['Days Tracked', str(len(summaries))],
                ['Total Readings', str(sum(s.get('reading_count', 0) or 0 for s in summaries))],
            ]

            stats_table = Table(stats_data, colWidths=[200, 150])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), STEEL_BLUE),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 1), (-1, -1), DARK_TEXT),
                ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(stats_table)
        else:
            elements.append(Paragraph("No data available for the selected period.", styles['BodyText2']))

        elements.append(PageBreak())

        # ===== Page 3: Zone Breakdown =====
        elements.append(Paragraph("Zone Distribution", styles['SectionHead']))

        if summaries:
            total_calm = sum(s.get('time_in_calm_min', 0) or 0 for s in summaries)
            total_steady = sum(s.get('time_in_steady_min', 0) or 0 for s in summaries)
            total_tense = sum(s.get('time_in_tense_min', 0) or 0 for s in summaries)
            total_stressed = sum(s.get('time_in_stressed_min', 0) or 0 for s in summaries)
            total_time = total_calm + total_steady + total_tense + total_stressed

            zone_data = [
                ['Zone', 'Minutes', 'Percentage'],
                ['Calm', f'{total_calm:.0f}', f'{total_calm/max(total_time,1)*100:.1f}%'],
                ['Steady', f'{total_steady:.0f}', f'{total_steady/max(total_time,1)*100:.1f}%'],
                ['Tense', f'{total_tense:.0f}', f'{total_tense/max(total_time,1)*100:.1f}%'],
                ['Stressed', f'{total_stressed:.0f}', f'{total_stressed/max(total_time,1)*100:.1f}%'],
            ]

            zone_table = Table(zone_data, colWidths=[160, 120, 120])
            zone_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), STEEL_BLUE),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 1), (-1, -1), DARK_TEXT),
                ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(zone_table)

        elements.append(PageBreak())

        # ===== Fetch readings for enriched pages =====
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        readings = []
        try:
            readings = self.db.get_readings(start_time=start_time, limit=5000) or []
        except Exception as e:
            logger.warning(f"Failed to load readings for report: {e}")

        def _safe_avg(values):
            clean = [v for v in values if v is not None]
            return round(sum(clean) / len(clean), 2) if clean else None

        # ===== Page 3 (new): Depression & Anxiety =====
        elements.append(Paragraph("Depression &amp; Anxiety Screening", styles['SectionHead']))

        phq9_values = [r.get("phq9_mapped") for r in readings if r.get("phq9_mapped") is not None]
        gad7_values = [r.get("gad7_mapped") for r in readings if r.get("gad7_mapped") is not None]
        avg_phq9 = _safe_avg(phq9_values)
        avg_gad7 = _safe_avg(gad7_values)

        def _phq9_category(score):
            if score is None:
                return "N/A"
            if score <= 4:
                return "Minimal"
            if score <= 9:
                return "Mild"
            if score <= 14:
                return "Moderate"
            if score <= 19:
                return "Moderately Severe"
            return "Severe"

        def _gad7_category(score):
            if score is None:
                return "N/A"
            if score <= 4:
                return "Minimal"
            if score <= 9:
                return "Mild"
            if score <= 14:
                return "Moderate"
            return "Severe"

        da_data = [
            ['Measure', 'Avg Score', 'Severity', 'Readings'],
            ['PHQ-9 (Depression)',
             f'{avg_phq9:.1f}' if avg_phq9 is not None else 'N/A',
             _phq9_category(avg_phq9),
             str(len(phq9_values))],
            ['GAD-7 (Anxiety)',
             f'{avg_gad7:.1f}' if avg_gad7 is not None else 'N/A',
             _gad7_category(avg_gad7),
             str(len(gad7_values))],
        ]

        da_table = Table(da_data, colWidths=[160, 90, 120, 80])
        da_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), STEEL_BLUE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 1), (-1, -1), DARK_TEXT),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(da_table)
        elements.append(Spacer(1, 12))

        elements.append(Paragraph("Scoring Reference", styles['SectionHead']))
        elements.append(Paragraph(
            "<b>PHQ-9 mapped</b>: 0-4 Minimal | 5-9 Mild | 10-14 Moderate | 15-19 Mod-Severe | 20-27 Severe",
            styles['BodyText2']
        ))
        elements.append(Paragraph(
            "<b>GAD-7 mapped</b>: 0-4 Minimal | 5-9 Mild | 10-14 Moderate | 15-21 Severe",
            styles['BodyText2']
        ))

        # Trend note
        if phq9_values and len(phq9_values) >= 2:
            midpoint = len(phq9_values) // 2
            first_half = _safe_avg(phq9_values[:midpoint])
            second_half = _safe_avg(phq9_values[midpoint:])
            if first_half is not None and second_half is not None:
                delta = second_half - first_half
                direction = "increasing" if delta > 0.5 else ("decreasing" if delta < -0.5 else "stable")
                elements.append(Spacer(1, 8))
                elements.append(Paragraph(
                    f"<b>PHQ-9 trend</b>: {direction} over the period "
                    f"(first half avg: {first_half:.1f}, second half avg: {second_half:.1f})",
                    styles['BodyText2']
                ))

        elements.append(PageBreak())

        # ===== Page 4 (new): Acoustic Profile =====
        elements.append(Paragraph("Acoustic Profile", styles['SectionHead']))
        elements.append(Paragraph(
            "Key voice biomarkers compared against population reference ranges.",
            styles['BodyText2']
        ))
        elements.append(Spacer(1, 8))

        avg_f0 = _safe_avg([r.get("f0_mean") for r in readings])
        avg_hnr = _safe_avg([r.get("hnr") for r in readings])
        avg_speech_rate = _safe_avg([r.get("speech_rate") for r in readings])
        avg_alpha = _safe_avg([r.get("alpha_ratio") for r in readings])

        def _format_val(val, unit=""):
            return f"{val:.1f}{unit}" if val is not None else "N/A"

        def _range_status(val, low, high):
            if val is None:
                return "Insufficient data"
            if val < low:
                return "Below normal"
            if val > high:
                return "Above normal"
            return "Within normal"

        acoustic_data = [
            ['Biomarker', 'Your Value', 'Normal Range', 'Status'],
            ['Fundamental Freq (F0)',
             _format_val(avg_f0, ' Hz'),
             '100-250 Hz',
             _range_status(avg_f0, 100, 250)],
            ['Harmonics-to-Noise (HNR)',
             _format_val(avg_hnr, ' dB'),
             '15-25 dB',
             _range_status(avg_hnr, 15, 25)],
            ['Speech Rate',
             _format_val(avg_speech_rate, ' wpm'),
             '120-180 wpm',
             _range_status(avg_speech_rate, 120, 180)],
            ['Alpha Ratio',
             _format_val(avg_alpha, ' dB'),
             '-15 to -5 dB',
             _range_status(avg_alpha, -15, -5)],
        ]

        acoustic_table = Table(acoustic_data, colWidths=[140, 100, 100, 110])
        acoustic_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), STEEL_BLUE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 1), (-1, -1), DARK_TEXT),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(acoustic_table)

        elements.append(PageBreak())

        # ===== Page 5 (new): Linguistic Markers =====
        elements.append(Paragraph("Linguistic Markers", styles['SectionHead']))
        elements.append(Paragraph(
            "Language patterns extracted from speech-to-text analysis with clinical interpretation.",
            styles['BodyText2']
        ))
        elements.append(Spacer(1, 8))

        avg_filler = _safe_avg([r.get("filler_rate") for r in readings])
        avg_hedging = _safe_avg([r.get("hedging_rate") for r in readings])
        avg_neg_sent = _safe_avg([r.get("negative_sentiment") for r in readings])
        avg_lex_div = _safe_avg([r.get("lexical_diversity") for r in readings])
        avg_pronoun_i = _safe_avg([r.get("pronoun_i_ratio") for r in readings])

        def _filler_interp(val):
            if val is None:
                return "Insufficient data"
            if val < 0.03:
                return "Low — fluent speech"
            if val < 0.08:
                return "Normal range"
            return "Elevated — may indicate cognitive load or anxiety"

        def _hedging_interp(val):
            if val is None:
                return "Insufficient data"
            if val < 0.03:
                return "Low — assertive speech"
            if val < 0.08:
                return "Normal range"
            return "Elevated — possible uncertainty or low confidence"

        def _neg_sent_interp(val):
            if val is None:
                return "Insufficient data"
            if val < 0.15:
                return "Low negativity"
            if val < 0.35:
                return "Moderate — within normal variation"
            return "Elevated — monitor for persistent negative affect"

        def _lex_div_interp(val):
            if val is None:
                return "Insufficient data"
            if val < 0.40:
                return "Contracted — may signal cognitive fatigue or depression"
            if val < 0.65:
                return "Normal range"
            return "Rich vocabulary"

        def _pronoun_interp(val):
            if val is None:
                return "Insufficient data"
            if val < 0.05:
                return "Low self-reference"
            if val <= 0.10:
                return "Normal range"
            return "Elevated self-focus — associated with depression in literature"

        ling_data = [
            ['Marker', 'Value', 'Clinical Interpretation'],
            ['Filler Rate',
             f'{avg_filler:.3f}' if avg_filler is not None else 'N/A',
             _filler_interp(avg_filler)],
            ['Hedging Rate',
             f'{avg_hedging:.3f}' if avg_hedging is not None else 'N/A',
             _hedging_interp(avg_hedging)],
            ['Negative Sentiment',
             f'{avg_neg_sent:.3f}' if avg_neg_sent is not None else 'N/A',
             _neg_sent_interp(avg_neg_sent)],
            ['Lexical Diversity',
             f'{avg_lex_div:.3f}' if avg_lex_div is not None else 'N/A',
             _lex_div_interp(avg_lex_div)],
            ['Pronoun-I Ratio',
             f'{avg_pronoun_i:.3f}' if avg_pronoun_i is not None else 'N/A',
             _pronoun_interp(avg_pronoun_i)],
        ]

        ling_table = Table(ling_data, colWidths=[110, 70, 270])
        ling_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), STEEL_BLUE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 1), (-1, -1), DARK_TEXT),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(ling_table)

        elements.append(PageBreak())

        # ===== Page 6 (new): Clinical Observations =====
        elements.append(Paragraph("Clinical Observations", styles['SectionHead']))
        elements.append(Paragraph(
            "Auto-generated narrative based on detected patterns and clinical thresholds. "
            "Intended as a screening aid — not a diagnosis.",
            styles['BodyText2']
        ))
        elements.append(Spacer(1, 12))

        observations = []

        # Stress overview
        stress_values = [s.get('avg_stress', 50) or 50 for s in summaries]
        overall_stress = sum(stress_values) / len(stress_values) if stress_values else None
        if overall_stress is not None:
            level = "low" if overall_stress < 35 else ("moderate" if overall_stress < 60 else "elevated")
            observations.append(
                f"Over the {days}-day period ({len(summaries)} days tracked), the average stress index "
                f"was <b>{overall_stress:.1f}</b>, categorized as <b>{level}</b>."
            )

        # Depression / anxiety
        if avg_phq9 is not None:
            cat = _phq9_category(avg_phq9)
            observations.append(
                f"Voice-mapped PHQ-9 averaged <b>{avg_phq9:.1f}</b> ({cat} severity). "
                + ("Clinical follow-up recommended." if avg_phq9 >= 10 else "")
            )
        if avg_gad7 is not None:
            cat = _gad7_category(avg_gad7)
            observations.append(
                f"Voice-mapped GAD-7 averaged <b>{avg_gad7:.1f}</b> ({cat} severity). "
                + ("Clinical follow-up recommended." if avg_gad7 >= 10 else "")
            )

        # Acoustic flags
        if avg_hnr is not None and avg_hnr < 15:
            observations.append(
                f"Harmonics-to-noise ratio ({avg_hnr:.1f} dB) is below the healthy range (15-25 dB), "
                "which may indicate vocal strain, fatigue, or dysphonia."
            )
        if avg_speech_rate is not None and avg_speech_rate < 120:
            observations.append(
                f"Speech rate ({avg_speech_rate:.0f} wpm) is below normal (120-180 wpm), "
                "potentially indicating psychomotor slowing."
            )

        # Linguistic flags
        if avg_pronoun_i is not None and avg_pronoun_i > 0.10:
            observations.append(
                f"Elevated self-referential language (pronoun-I ratio: {avg_pronoun_i:.3f}) detected. "
                "Research associates heightened self-focus with depressive states."
            )
        if avg_lex_div is not None and avg_lex_div < 0.40:
            observations.append(
                f"Lexical diversity ({avg_lex_div:.3f}) is contracted, which may signal "
                "cognitive fatigue, rumination, or depressive symptoms."
            )
        if avg_neg_sent is not None and avg_neg_sent > 0.35:
            observations.append(
                f"Negative sentiment proportion ({avg_neg_sent:.3f}) is elevated. "
                "Persistent negative affect warrants clinical attention."
            )

        # Week-over-week stress trend
        if readings:
            now_date = date.today()
            last7 = [r.get("stress") for r in readings
                      if r.get("timestamp") and r["timestamp"][:10] >= (now_date - timedelta(days=7)).isoformat()
                      and r.get("stress") is not None]
            prior7 = [r.get("stress") for r in readings
                       if r.get("timestamp")
                       and (now_date - timedelta(days=14)).isoformat() <= r["timestamp"][:10] < (now_date - timedelta(days=7)).isoformat()
                       and r.get("stress") is not None]
            if last7 and prior7:
                last_avg = sum(last7) / len(last7)
                prior_avg = sum(prior7) / len(prior7)
                delta = last_avg - prior_avg
                if abs(delta) >= 5:
                    direction = "increased" if delta > 0 else "decreased"
                    observations.append(
                        f"Week-over-week stress {direction} by <b>{abs(delta):.1f}</b> points "
                        f"(prior 7d: {prior_avg:.1f} → last 7d: {last_avg:.1f})."
                    )

        if not observations:
            observations.append("No notable clinical patterns detected during this period.")

        for obs in observations:
            elements.append(Paragraph(f"• {obs}", styles['BodyText2']))
            elements.append(Spacer(1, 4))

        elements.append(Spacer(1, 24))

        # Footer
        elements.append(Paragraph(
            "For clinical review. Extracted from voice pattern analysis. "
            "This is not a medical diagnosis.",
            styles['Footer']
        ))

        # Build PDF
        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        logger.info(f"Generated wellness report: {len(pdf_bytes)} bytes, {days} days, {len(summaries)} summaries")
        return pdf_bytes

    def _build_stress_chart(self, summaries: List[Dict]) -> Drawing:
        """Build a stress trend line chart."""
        width = 480
        height = 200
        d = Drawing(width, height)

        # Background
        d.add(Rect(0, 0, width, height, fillColor=LIGHT_BG, strokeColor=None))

        if not summaries:
            return d

        # Plot data
        stress_data = [(i, s.get('avg_stress', 50) or 50) for i, s in enumerate(summaries)]

        chart = LinePlot()
        chart.x = 40
        chart.y = 30
        chart.width = width - 60
        chart.height = height - 50

        chart.data = [[(x, y) for x, y in stress_data]]
        chart.lines[0].strokeColor = STEEL_BLUE
        chart.lines[0].strokeWidth = 2

        # Axes
        chart.xValueAxis.visible = False
        chart.yValueAxis.valueMin = 0
        chart.yValueAxis.valueMax = 100
        chart.yValueAxis.valueStep = 25
        chart.yValueAxis.labels.fontSize = 8
        chart.yValueAxis.labels.fillColor = BODY_TEXT
        chart.yValueAxis.strokeColor = BORDER_GRAY

        d.add(chart)

        # Date labels (first and last)
        if summaries:
            d.add(String(40, 10, summaries[0]['date'], fontSize=8, fillColor=BODY_TEXT))
            d.add(String(width - 80, 10, summaries[-1]['date'], fontSize=8, fillColor=BODY_TEXT))

        return d
