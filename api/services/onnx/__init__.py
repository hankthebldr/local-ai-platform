"""ONNX Runtime execution substrate for Enclave's encoder tier.

Hardware-portable embeddings / rerankers / classifiers. Selects execution
providers per host from api.services.architecture. Sits beside the Runner
axis (LLM generation) — it is NOT a Runner.
"""
