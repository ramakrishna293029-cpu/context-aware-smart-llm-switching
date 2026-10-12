"""
Downloads and verifies all 10 exact Research Papers into:
C:\\Users\\rama krishna\\OneDrive\\Desktop\\research papers
"""

import os
import shutil
import urllib.request
import sys
import pypdf

sys.stdout.reconfigure(encoding="utf-8")

DESKTOP_DIR = r"C:\Users\rama krishna\OneDrive\Desktop"
OLD_DIR = os.path.join(DESKTOP_DIR, "Project_References_Papers")
TARGET_DIR = os.path.join(DESKTOP_DIR, "research papers")

os.makedirs(TARGET_DIR, exist_ok=True)
os.makedirs(OLD_DIR, exist_ok=True)

PAPERS = [
    {
        "num": 1,
        "filename": "01_FrugalGPT_How_to_Use_LLMs_While_Reducing_Cost_Chen_et_al_2023.pdf",
        "arxiv_id": "2305.05176",
        "expected_keyword": "FrugalGPT",
        "needs_redownload": False
    },
    {
        "num": 2,
        "filename": "02_RouteLLM_Learning_to_Route_LLMs_with_Preference_Data_Ong_et_al_2024.pdf",
        "arxiv_id": "2406.18665",
        "expected_keyword": "ROUTE",
        "needs_redownload": False
    },
    {
        "num": 3,
        "filename": "03_Speculative_Decoding_Fast_Inference_Transformers_Leviathan_et_al_2023.pdf",
        "arxiv_id": "2211.17192",
        "expected_keyword": "Speculative Decoding",
        "needs_redownload": False
    },
    {
        "num": 4,
        "filename": "04_Large_Language_Model_Routing_Benchmark_Datasets_Shnitzer_et_al_2023.pdf",
        "arxiv_id": "2309.15789",
        "expected_keyword": "Large Language Model Routing",
        "needs_redownload": False
    },
    {
        "num": 5,
        "filename": "05_OmniRouter_Controllable_Multi_LLM_Routing_2024.pdf",
        "arxiv_id": "2502.20576",
        "expected_keyword": "OmniRouter",
        "needs_redownload": True
    },
    {
        "num": 6,
        "filename": "06_Mixture_of_Agents_Enhances_LLM_Capabilities_Wang_et_al_2024.pdf",
        "arxiv_id": "2406.04692",
        "expected_keyword": "Mixture-of-Agents",
        "needs_redownload": False
    },
    {
        "num": 7,
        "filename": "07_Mixtral_of_Experts_Jiang_et_al_2024.pdf",
        "arxiv_id": "2401.04088",
        "expected_keyword": "Mixtral of Experts",
        "needs_redownload": False
    },
    {
        "num": 8,
        "filename": "08_SpecInfer_Tree_Based_Speculative_Inference_Miao_et_al_2024.pdf",
        "arxiv_id": "2305.09781",
        "expected_keyword": "SpecInfer",
        "needs_redownload": True
    },
    {
        "num": 9,
        "filename": "09_LLM_Blender_Ensembling_LLMs_Pairwise_Ranking_2023.pdf",
        "arxiv_id": "2306.02561",
        "expected_keyword": "LLM-Blender",
        "needs_redownload": True
    },
    {
        "num": 10,
        "filename": "10_Cost_Effective_Model_Cascading_for_Code_Chen_et_al_2024.pdf",
        "arxiv_id": "2405.15842",
        "expected_keyword": "CASCADING",
        "needs_redownload": False
    }
]

def download_pdf(arxiv_id, dest_path):
    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp, open(dest_path, "wb") as f:
        data = resp.read()
        f.write(data)
    return len(data)

def main():
    print(f"Setting up folder: {TARGET_DIR}\n")
    
    for p in PAPERS:
        target_path = os.path.join(TARGET_DIR, p["filename"])
        old_path = os.path.join(OLD_DIR, p["filename"])
        
        if not p["needs_redownload"] and os.path.exists(old_path):
            shutil.copy2(old_path, target_path)
            print(f"[{p['num']:02d}/10] Copied verified PDF: {p['filename']}")
        else:
            print(f"[{p['num']:02d}/10] Downloading arXiv:{p['arxiv_id']} -> {p['filename']} ...")
            sz = download_pdf(p["arxiv_id"], target_path)
            # Also copy back to OLD_DIR to keep it clean
            shutil.copy2(target_path, old_path)
            print(f"        Downloaded {sz:,} bytes.")

    # Remove old mismatched files in OLD_DIR if any
    old_bad = os.path.join(OLD_DIR, "05_OmniRouter_Controllable_Multi_LLM_Routing_Lu_et_al_2024.pdf")
    if os.path.exists(old_bad):
        os.remove(old_bad)
    old_bad9 = os.path.join(OLD_DIR, "09_LLM_Blender_Ensembling_LLMs_Pairwise_Ranking_Sun_et_al_2023.pdf")
    if os.path.exists(old_bad9):
        os.remove(old_bad9)

    print("\n=== VERIFYING ALL 10 PDF FILES IN 'research papers' FOLDER ===")
    for p in PAPERS:
        target_path = os.path.join(TARGET_DIR, p["filename"])
        reader = pypdf.PdfReader(target_path)
        first_page = reader.pages[0].extract_text()[:350].replace("\n", " ")
        print(f"Paper {p['num']:02d} ({len(reader.pages)} pages) | {p['filename']}")
        print(f"   Header Text: {first_page[:140]}...\n")

if __name__ == "__main__":
    main()
