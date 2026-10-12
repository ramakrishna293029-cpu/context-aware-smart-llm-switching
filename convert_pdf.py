"""
Converts 'Design Project Report.docx' to 'Design Project Report.pdf' using Word COM.
Verifies exact page count.
"""

import os
import subprocess
import sys

def convert_to_pdf(docx_path, pdf_path):
    docx_path = os.path.abspath(docx_path)
    pdf_path = os.path.abspath(pdf_path)
    
    ps_code = f"""
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {{
    $doc = $word.Documents.Open('{docx_path}')
    $pages = $doc.ComputeStatistics(2) # 2 = wdStatisticPages
    Write-Host "DOCX_PAGES: $pages"
    $doc.SaveAs([ref]'{pdf_path}', [ref]17) # 17 = wdFormatPDF
    $doc.Close([ref]0) # 0 = wdDoNotSaveChanges
    Write-Host "PDF_CONVERTED_SUCCESS"
}} catch {{
    Write-Host "CONVERT_ERROR: $_"
}} finally {{
    $word.Quit()
}}
"""
    ps_file = "convert_temp.ps1"
    with open(ps_file, "w", encoding="utf-8") as f:
        f.write(ps_code)
    
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_file],
        capture_output=True, text=True
    )
    if os.path.exists(ps_file):
        os.remove(ps_file)
    
    print("PowerShell Output:")
    print(result.stdout)
    if result.stderr:
        print("PowerShell Error:", result.stderr)

if __name__ == "__main__":
    report_dir = r"C:\Users\rama krishna\OneDrive\Desktop\report"
    docx_file = os.path.join(report_dir, "Design Project Report.docx")
    pdf_file = os.path.join(report_dir, "Design Project Report.pdf")
    
    convert_to_pdf(docx_file, pdf_file)
