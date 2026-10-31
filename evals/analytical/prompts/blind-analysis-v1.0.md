# Blind analytical evaluation prompt

Prompt version: `blind-analysis-v1.0`

Analyze the explicitly named `dataset.csv` and identify the most important findings supported by its observed data. Treat the column labels as the only available context: do not invent a business domain or causal explanation. Distinguish direct observations from interpretation, state uncertainty where evidence is incomplete, and avoid claiming a sustained trend from too few periods.

Return one JSON object only, with this shape:

```json
{
  "schema_version": 1,
  "summary": "Short decision-ready overview",
  "semantics": {
    "observation_grain": ["column names that identify one observed row"],
    "entity_fields": ["columns that appear to identify repeated entities"],
    "time_fields": ["columns that represent time"],
    "measure_fields": ["numeric columns that can be measured"]
  },
  "questions": ["Useful follow-up analytical questions"],
  "facts": [
    {"id": "f1", "statement": "Observed or calculated fact", "value": 0,
     "unit": "unit or unknown", "evidence_columns": ["column"]}
  ],
  "findings": [
    {"statement": "Material interpretation", "materiality": "HIGH|MEDIUM|LOW|UNKNOWN",
     "confidence": "HIGH|MEDIUM|LOW|UNKNOWN", "evidence_fact_ids": ["f1"],
     "evidence_columns": ["column"]}
  ],
  "claims": [
    {"text": "A concise claim", "evidence_fact_ids": ["f1"],
     "strength": "OBSERVED|DERIVED|SUPPORTED|INFERRED|HYPOTHESIS|UNKNOWN", "material": true}
  ],
  "surfaces": {
    "direct": [{"fact_id": "f1", "value": 0, "unit": "unit or unknown"}],
    "report": [{"fact_id": "f1", "value": 0, "unit": "unit or unknown"}],
    "presentation": [{"fact_id": "f1", "value": 0, "unit": "unit or unknown"}]
  },
  "limitations": ["Material data or inference limitations"]
}
```

Use only evidence from this dataset. Keep identifiers unique within `facts`; every finding and claim should point to facts that you define. The three surface lists may be empty if no corresponding output was produced. Do not include hidden reasoning or private chain-of-thought; concise evidence and conclusions are sufficient.
