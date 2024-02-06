from typing import Any, Optional, Dict, List
import pandas as pd
from transformers import AutoTokenizer
from tqdm import tqdm
from langchain_core.embeddings import Embeddings
from langchain_core.pydantic_v1 import BaseModel, Extra
from optimum.intel import INCModel
import torch

class QuantizedBiEncoderEmbeddings(BaseModel, Embeddings):
    """HuggingFace sentence_transformers embedding models.

    To use, you should have the ``optimum-intel`` python package installed.

    Example:
        .. code-block:: python

            from langchain_community.embeddings import QuantizedBiEncoderEmbeddings

            model_name = "Intel/bge-large-en-v1.5-rag-int8-static"
            model_kwargs = {'device': 'cpu'}
            encode_kwargs = {'normalize_embeddings': True}
            hf = QuantizedBiEncoderEmbeddings(
                model_name=model_name,
                model_kwargs=model_kwargs,
                encode_kwargs=encode_kwargs,
                query_instruction="Represent this sentence for searching relevant passages: "
            )
    """    
    def __init__(self, 
                 max_seq_len: int = 512,
                 pooling_strategy: str = "mean",  # "mean" or "cls"
                 query_instruction: Optional[str] = None,
                 document_instruction: Optional[str] = None,
                 padding: Optional[bool] = True,
                 use_auth_token: Optional[bool] = False,
                 model_kwargs: Optional[Dict] = {},
                 encode_kwargs: Optional[Dict] = {},
                 **kwargs: Any):
        super().__init__(**kwargs)
        self.model_name_or_path = self.model_name
        self.use_auth_token = use_auth_token
        self.max_seq_len = max_seq_len
        self.pooling = pooling_strategy
        self.padding = padding
        self.encode_kwargs = encode_kwargs
        self.model_kwargs = model_kwargs
        self.normalize = self.encode_kwargs.get("normalize_embeddings", False)
        self.batch_size= self.encode_kwargs.get("batch_size", 32)
        
        self.query_instruction = query_instruction
        self.document_instruction = document_instruction
        
        self.warm_up()

    def warm_up(self):
        try:
            self.transformer_model = INCModel.from_pretrained(self.model_name_or_path, **self.model_kwargs)
        except:
            raise Exception(
                f"Failed to load an optimized INCModel from {self.model_name_or_path}"
            )
        self.transformer_tokenizer = AutoTokenizer.from_pretrained(
            pretrained_model_name_or_path=self.model_name_or_path,
        )
        self.transformer_model.eval()
        
    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.allow

    def _embed(self, inputs):
        with torch.inference_mode():
            outputs = self.transformer_model(**inputs)
            if self.pooling == "mean":
                emb = self._mean_pooling(outputs, inputs["attention_mask"])
            elif self.pooling == "cls":
                emb = self._cls_pooling(outputs)
            else:
                raise ValueError("pooling method no supported")

            if self.normalize:
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            return emb

    @staticmethod
    def _cls_pooling(outputs):
        if type(outputs) == dict:
            token_embeddings = outputs["last_hidden_state"]
        else:
            token_embeddings = outputs[0]
        return token_embeddings[:, 0]

    @staticmethod
    def _mean_pooling(outputs, attention_mask):
        if type(outputs) == dict:
            token_embeddings = outputs["last_hidden_state"]
        else:
            # First element of model_output contains all token embeddings
            token_embeddings = outputs[0]
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        return sum_embeddings / sum_mask

    def _embed_text(self, texts: List[str]) -> List[List[float]]:
        inputs = self.transformer_tokenizer(
            texts,
            max_length = self.max_seq_len,
            truncation=True,
            padding=self.padding,
            return_tensors="pt",
        )
        return self._embed(inputs).tolist()
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Compute doc embeddings using the Optimized Embedder model.

        Args:
            texts: The list of texts to embed.

        Returns:
            List of embeddings, one for each text.
        """
        docs = [
            self.document_instruction + d.content if self.document_instruction else d
            for d in texts
        ]

        # group into batches
        text_list_df = pd.DataFrame(docs, columns=["texts"]).reset_index()

        # assign each example with its batch 
        text_list_df["batch_index"] = text_list_df["index"] // self.batch_size

        # create groups
        batches = list(text_list_df.groupby(["batch_index"])["texts"].apply(list))

        vectors = []
        for batch in tqdm(batches, desc="Batches"):
            vectors += self._embed_text(batch)
        return vectors

    def embed_query(self, text: str) -> List[float]:
        """Compute query embeddings using the Optimized Embedder model.

        Args:
            text: The text to embed.

        Returns:
            Embeddings for the text.
        """
        if self.query_instruction:
            text = self.query_instruction + text
        return self._embed_text([text])[0]

