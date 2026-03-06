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
        elements.append(Paragraph("Voice Wellness Report", styles['CoverTitle']))

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
