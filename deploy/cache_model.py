"""Fetch only the pinned embedding model runtime files into the private cache."""
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id='BAAI/bge-m3',
    revision='5617a9f61b028005a4858fdac845db406aefb181',
    allow_patterns=['*.json', '*.safetensors', 'pytorch_model.bin', 'sentencepiece.bpe.model', '1_Pooling/*'],
    ignore_patterns=['onnx/*', 'openvino/*'],
)
print('Pinned BGE-M3 runtime snapshot cached.')
