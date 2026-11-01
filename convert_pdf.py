import os
import sys
import time

# Kill any lingering PowerPoint processes first
os.system("taskkill /f /im POWERPNT.EXE 2>nul")
time.sleep(1)

import win32com.client
import pythoncom

pythoncom.CoInitialize()
ppt = win32com.client.Dispatch("PowerPoint.Application")
ppt.Visible = 1

pptx_path = os.path.abspath(r"C:\Users\rama krishna\OneDrive\Desktop\design project final PPT.pptx")
pdf_path = os.path.abspath(r"C:\Users\rama krishna\OneDrive\Desktop\design project final PPT.pdf")
pdf_ws = os.path.abspath(r"design project final PPT.pdf")

print(f"Opening: {pptx_path}")
pres = ppt.Presentations.Open(pptx_path, WithWindow=True)
time.sleep(0.5)

print(f"Saving to: {pdf_path}")
pres.SaveAs(pdf_path, 32) # ppSaveAsPDF = 32
pres.Close()
ppt.Quit()
pythoncom.CoUninitialize()

import shutil
shutil.copyfile(pdf_path, pdf_ws)
print("SUCCESS: PDF converted and copied to workspace!")
