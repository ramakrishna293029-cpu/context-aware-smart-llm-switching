"""
Downloader for all 10 Reference Research Papers.
Saves directly to: C:\\Users\\rama krishna\\OneDrive\\Desktop\\Project_References_Papers
"""

import os
import urllib.request
import time

DESKTOP_DIR = r"C:\Users\rama krishna\OneDrive\Desktop"
TARGET_DIR = os.path.join(DESKTOP_DIR, "Project_References_Papers")
os.makedirs(TARGET_DIR, exist_ok=True)

PAPERS = [
    {
        "num": 1,
        "filename": "01_FrugalGPT_How_to_Use_LLMs_While_Reducing_Cost_Chen_et_al_2023.pdf",
        "title": "FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance",
        "authors": "Lingjiao Chen, Matei Zaharia, James Zou (Stanford University)",
        "venue": "arXiv preprint arXiv:2305.05176",
        "url": "https://arxiv.org/pdf/2305.05176.pdf"
    },
    {
        "num": 2,
        "filename": "02_RouteLLM_Learning_to_Route_LLMs_with_Preference_Data_Ong_et_al_2024.pdf",
        "title": "RouteLLM: Learning to Route LLMs with Preference Data",
        "authors": "Derek C. Ong et al. (LMSYS Organization & UC Berkeley)",
        "venue": "arXiv preprint arXiv:2406.18665",
        "url": "https://arxiv.org/pdf/2406.18665.pdf"
    },
    {
        "num": 3,
        "filename": "03_Speculative_Decoding_Fast_Inference_Transformers_Leviathan_et_al_2023.pdf",
        "title": "Fast Inference from Transformers via Speculative Decoding",
        "authors": "Yaniv Leviathan, Matan Kalman, Yossi Matias (Google Research)",
        "venue": "ICML 2023 / PMLR 202:19274-19286 / arXiv:2211.17192",
        "url": "https://arxiv.org/pdf/2211.17192.pdf"
    },
    {
        "num": 4,
        "filename": "04_Large_Language_Model_Routing_Benchmark_Datasets_Shnitzer_et_al_2023.pdf",
        "title": "Large Language Model Routing with Benchmark Datasets",
        "authors": "Tal Shnitzer et al. (IBM Research & Technion)",
        "venue": "NeurIPS Workshop on Efficient Natural Language and Speech Processing (ENLSP) / arXiv:2309.15789",
        "url": "https://arxiv.org/pdf/2309.15789.pdf"
    },
    {
        "num": 5,
        "filename": "05_OmniRouter_Controllable_Multi_LLM_Routing_Lu_et_al_2024.pdf",
        "title": "OmniRouter: Budget and Performance Controllable Multi-LLM Routing",
        "authors": "K. Lu, et al.",
        "venue": "ACM SIGKDD / arXiv:2407.03150",
        "url": "https://arxiv.org/pdf/2407.03150.pdf"
    },
    {
        "num": 6,
        "filename": "06_Mixture_of_Agents_Enhances_LLM_Capabilities_Wang_et_al_2024.pdf",
        "title": "Mixture-of-Agents Enhances Large Language Model Capabilities",
        "authors": "Junjie Wang et al. (Together AI Research)",
        "venue": "arXiv preprint arXiv:2406.04692",
        "url": "https://arxiv.org/pdf/2406.04692.pdf"
    },
    {
        "num": 7,
        "filename": "07_Mixtral_of_Experts_Jiang_et_al_2024.pdf",
        "title": "Mixtral of Experts",
        "authors": "Albert Q. Jiang et al. (Mistral AI Research)",
        "venue": "arXiv preprint arXiv:2401.04088",
        "url": "https://arxiv.org/pdf/2401.04088.pdf"
    },
    {
        "num": 8,
        "filename": "08_SpecInfer_Tree_Based_Speculative_Inference_Miao_et_al_2024.pdf",
        "title": "SpecInfer: Accelerating Generative LLM Serving with Tree-based Speculative Inference and Verification",
        "authors": "Xupeng Miao et al. (Carnegie Mellon & UCSD)",
        "venue": "ACM ASPLOS 2024 / arXiv:2305.09780",
        "url": "https://arxiv.org/pdf/2305.09780.pdf"
    },
    {
        "num": 9,
        "filename": "09_LLM_Blender_Ensembling_LLMs_Pairwise_Ranking_Sun_et_al_2023.pdf",
        "title": "LLM-Blender: Ensembling Large Language Models with Pairwise Ranking and Generative Fusion",
        "authors": "Dongfu Jiang, Xiang Ren, et al. / M. Sun et al.",
        "venue": "Findings of ACL 2023 / arXiv:2306.02531",
        "url": "https://arxiv.org/pdf/2306.02531.pdf"
    },
    {
        "num": 10,
        "filename": "10_Cost_Effective_Model_Cascading_for_Code_Chen_et_al_2024.pdf",
        "title": "Reducing Inference Costs with Model Cascading for LLM Based Code Generation",
        "authors": "C. Chen, et al.",
        "venue": "arXiv:2405.15842 / PVLDB",
        "url": "https://arxiv.org/pdf/2405.15842.pdf"
    }
]

def download_file(url, target_path):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response, open(target_path, "wb") as out_file:
        data = response.read()
        out_file.write(data)
    return len(data)

def main():
    print(f"Target Directory: {TARGET_DIR}")
    results = []
    
    for p in PAPERS:
        file_path = os.path.join(TARGET_DIR, p["filename"])
        print(f"[{p['num']}/10] Downloading: {p['title'][:60]}...")
        try:
            sz = download_file(p["url"], file_path)
            # Verify magic bytes
            with open(file_path, "rb") as f:
                header = f.read(5)
            is_valid = header.startswith(b"%PDF")
            print(f"     -> Saved: {p['filename']} ({sz:,} bytes) [Valid PDF: {is_valid}]")
            results.append((p, True, sz))
        except Exception as e:
            print(f"     -> ERROR: {e}")
            results.append((p, False, str(e)))
        time.sleep(1) # Be gentle to servers

    # Generate an Index Document inside the folder
    index_md_path = os.path.join(TARGET_DIR, "README_REFERENCES_INDEX.md")
    with open(index_md_path, "w", encoding="utf-8") as f:
        f.write("# References & Research Literature\n")
        f.write("## Context-Aware Smart LLM Switching for Cost and Performance Optimization\n\n")
        f.write("| # | Paper Title | Authors & Venue | Downloaded File |\n")
        f.write("|---|---|---|---|\n")
        for p, success, val in results:
            if success:
                f.write(f"| {p['num']} | **{p['title']}** | {p['authors']} ({p['venue']}) | `{p['filename']}` ({val:,} bytes) |\n")
            else:
                f.write(f"| {p['num']} | **{p['title']}** | {p['authors']} ({p['venue']}) | Failed: {val} |\n")
    
    print("\nAll downloads completed! Index created at:", index_md_path)

if __name__ == "__main__":
    main()
