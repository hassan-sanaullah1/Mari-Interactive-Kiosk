# server/data

Grounding corpus for the kiosk assistant, loaded by [`server/knowledge.py`](../knowledge.py).

- `mari_energies_knowledge_base.md` — Mari Energies Limited knowledge base, converted from
  the source `MariEnergies_RAG_Knowledge_Base_V2.docx`. Retrieval keys off `##`/`###`
  headings, so keep the numbered section structure (`## 1. …` / `### 1.4 …`) when editing:
  each heading becomes one retrievable chunk, and its text is weighted into the ranking.

- `../data_originals/mari_energies_knowledge_base_original.md` — untouched copy of the
  corpus as it stood before Section 3.1.3 was expanded with Sky47's cloud, AI and Huawei
  material. Kept for reference only; nothing loads it.
- `sky47_knowledge_base.md` — the fuller Sky47 corpus that §3.1.3 was summarised from.
  Not loaded by the kiosk.

Point `APP_KNOWLEDGE_FILE` at a different markdown file to swap the corpus without a code
change.
