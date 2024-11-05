import argparse
import json
import os
from pathlib import Path
from typing import Any, List, Optional  # noqa: E402

import torch  # noqa
from comet_ml import Artifact, Experiment
from comet_ml.artifacts import ArtifactAsset
from datasets import Dataset, concatenate_datasets, load_dataset  # noqa: E402
from huggingface_hub import HfApi  # noqa: E402
from huggingface_hub.utils import RepositoryNotFoundError  # noqa: E402
from transformers import TextStreamer, TrainingArguments  # noqa: E402
from trl import SFTTrainer  # noqa: E402
from unsloth import FastLanguageModel, is_bfloat16_supported  # noqa: E402
from unsloth.chat_templates import get_chat_template  # noqa: E402

ALPACA_TEMPLATE = """Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
{}

### Response:
{}"""


class DatasetClient:
    def __init__(
        self,
        output_dir: Path = Path("./finetuning_dataset"),
    ) -> None:
        # self.experiment = Experiment(
        #     api_key=settings.COMET_API_KEY,
        #     workspace=settings.COMET_WORKSPACE,
        #     project_name=settings.COMET_PROJECT,
        # )
        self.experiment = Experiment()

        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_dataset(self, artifact_name: str) -> Dataset:
        artifact = self._download_artifact(artifact_name)
        asset = self._artifact_to_asset(artifact)
        dataset = self._load_data(asset)

        return dataset

    def _download_artifact(self, artifact_name: str) -> Artifact:
        try:
            logged_artifact = self.experiment.get_artifact(artifact_name)
            artifact = logged_artifact.download(self.output_dir)
        except Exception as e:
            print(f"Error retrieving artifact: {str(e)}")

            raise

        self.experiment.end()

        print(f"Successfully downloaded  {artifact_name} at location {self.output_dir}")

        return artifact

    def _artifact_to_asset(self, artifact: Artifact) -> ArtifactAsset:
        if len(artifact.assets) == 0:
            raise RuntimeError("Artifact has no assets")
        elif len(artifact.assets) > 1:
            raise RuntimeError("Artifact has more than one asset")
        else:
            asset = artifact.assets[0]

        return asset

    def _load_data(self, asset: ArtifactAsset) -> Dataset:
        data_file_path = asset.local_path_or_data
        with open(data_file_path, "r") as file:
            data = json.load(file)

        dataset_dict = {k: [str(d[k]) for d in data] for k in data[0].keys()}
        dataset = Dataset.from_dict(dataset_dict)

        print(
            f"Successfully loaded dataset from artifact, num_samples = {len(dataset)}",
        )

        return dataset


def load_model(
    model_name: str,
    max_seq_length: int,
    load_in_4bit: bool,
    lora_rank: int,
    lora_alpha: int,
    lora_dropout: float,
    target_modules: List[str],
    chat_template: str,
) -> tuple:
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=max_seq_length,
        load_in_4bit=load_in_4bit,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_rank,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        target_modules=target_modules,
    )

    tokenizer = get_chat_template(
        tokenizer,
        chat_template=chat_template,
    )

    return model, tokenizer


def finetune(
    model_name: str,
    output_dir: str,
    dataset_huggingface_workspace: str,
    max_seq_length: int = 2048,
    load_in_4bit: bool = False,
    lora_rank: int = 32,
    lora_alpha: int = 32,
    lora_dropout: float = 0.0,
    target_modules: List[str] = [
        "q_proj",
        "k_proj",
        "v_proj",
        "up_proj",
        "down_proj",
        "o_proj",
        "gate_proj",
    ],  # noqa: B006
    chat_template: str = "chatml",
    learning_rate: float = 3e-4,
    num_train_epochs: int = 3,
    per_device_train_batch_size: int = 2,
    gradient_accumulation_steps: int = 8,
    is_dummy: bool = True,
) -> tuple:
    model, tokenizer = load_model(
        model_name,
        max_seq_length,
        load_in_4bit,
        lora_rank,
        lora_alpha,
        lora_dropout,
        target_modules,
        chat_template,
    )
    EOS_TOKEN = tokenizer.eos_token
    print(f"Setting EOS_TOKEN to {EOS_TOKEN}")  # noqa

    if is_dummy is True:
        num_train_epochs = 1
        print(
            f"Training in dummy mode. Setting num_train_epochs to '{num_train_epochs}'"
        )  # noqa
        print(f"Training in dummy mode. Reducing dataset size to '400'.")  # noqa

    def format_samples_sft(examples):
        text = []
        for instruction, output in zip(
            examples["instruction"], examples["content"], strict=False
        ):
            message = ALPACA_TEMPLATE.format(instruction, output) + EOS_TOKEN
            text.append(message)

        return {"text": text}

    dataset_client = DatasetClient()
    custom_dataset = dataset_client.download_dataset(
        artifact_name="posts-instruct-dataset"
    )
    static_dataset = load_dataset("mlabonne/FineTome-Alpaca-100k", split="train[:10000]")
    dataset = concatenate_datasets([custom_dataset, static_dataset])
    if is_dummy:
        dataset = dataset.select(range(400))
    print(f"Loaded dataset with {len(dataset)} samples.")  # noqa

    dataset = dataset.map(
        format_samples_sft, batched=True, remove_columns=dataset.column_names
    )
    dataset = dataset.train_test_split(test_size=0.05)

    print("Training dataset example:")  # noqa
    print(dataset["train"][0])  # noqa

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["test"],
        dataset_text_field="text",
        max_seq_length=max_seq_length,
        dataset_num_proc=2,
        packing=True,
        args=TrainingArguments(
            learning_rate=learning_rate,
            num_train_epochs=num_train_epochs,
            per_device_train_batch_size=per_device_train_batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            fp16=not is_bfloat16_supported(),
            bf16=is_bfloat16_supported(),
            logging_steps=1,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="linear",
            per_device_eval_batch_size=per_device_train_batch_size,
            warmup_steps=10,
            output_dir=output_dir,
            report_to="comet_ml",
            seed=0,
        ),
    )

    trainer.train()

    return model, tokenizer


def inference(
    model: Any,
    tokenizer: Any,
    prompt: str = "Write a paragraph to introduce supervised fine-tuning.",
    max_new_tokens: int = 256,
) -> None:
    model = FastLanguageModel.for_inference(model)
    message = ALPACA_TEMPLATE.format(prompt, "")
    inputs = tokenizer([message], return_tensors="pt").to("cuda")

    text_streamer = TextStreamer(tokenizer)
    _ = model.generate(
        **inputs, streamer=text_streamer, max_new_tokens=max_new_tokens, use_cache=True
    )


def save_model(
    model: Any,
    tokenizer: Any,
    output_dir: str,
    push_to_hub: bool = False,
    repo_id: Optional[str] = None,
) -> None:
    model.save_pretrained_merged(output_dir, tokenizer, save_method="merged_16bit")

    if push_to_hub and repo_id:
        print(f"Saving model to '{repo_id}'")  # noqa
        model.push_to_hub_merged(repo_id, tokenizer, save_method="merged_16bit")


def check_if_huggingface_model_exists(
    model_id: str, default_value: str = "mlabonne/TwinLlama-3.1-8B"
) -> str:
    api = HfApi()

    try:
        api.model_info(model_id)
    except RepositoryNotFoundError:
        print(f"Model '{model_id}' does not exist.")  # noqa
        model_id = default_value
        print(f"Defaulting to '{model_id}'")  # noqa
        print("Train your own 'TwinLlama-3.1-8B' to avoid this behavior.")  # noqa

    return model_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--num_train_epochs", type=int, default=3)
    parser.add_argument("--per_device_train_batch_size", type=int, default=2)
    parser.add_argument("--learning_rate", type=float, default=3e-4)
    parser.add_argument("--dataset_huggingface_workspace", type=str, default="mlabonne")
    parser.add_argument(
        "--model_output_huggingface_workspace", type=str, default="mlabonne"
    )
    parser.add_argument(
        "--is_dummy",
        type=bool,
        default=False,
        help="Flag to reduce the dataset size for testing",
    )
    parser.add_argument(
        "--finetuning_type",
        type=str,
        choices=["sft", "dpo"],
        default="sft",
        help="Parameter to choose the finetuning stage.",
    )

    parser.add_argument(
        "--output_data_dir", type=str, default=os.environ["SM_OUTPUT_DATA_DIR"]
    )
    parser.add_argument("--model_dir", type=str, default=os.environ["SM_MODEL_DIR"])
    parser.add_argument("--n_gpus", type=str, default=os.environ["SM_NUM_GPUS"])

    args = parser.parse_args()

    print(f"Num training epochs: '{args.num_train_epochs}'")  # noqa
    print(f"Per device train batch size: '{args.per_device_train_batch_size}'")  # noqa
    print(f"Learning rate: {args.learning_rate}")  # noqa
    print(
        f"Datasets will be loaded from Hugging Face workspace: '{args.dataset_huggingface_workspace}'"
    )  # noqa
    print(
        f"Models will be saved to Hugging Face workspace: '{args.model_output_huggingface_workspace}'"
    )  # noqa
    print(f"Training in dummy mode? '{args.is_dummy}'")  # noqa
    print(f"Finetuning type: '{args.finetuning_type}'")  # noqa

    print(f"Output data dir: '{args.output_data_dir}'")  # noqa
    print(f"Model dir: '{args.model_dir}'")  # noqa
    print(f"Number of GPUs: '{args.n_gpus}'")  # noqa

    print("Starting SFT training...")  # noqa
    base_model_name = "meta-llama/Meta-Llama-3.1-8B"
    print(f"Training from base model '{base_model_name}'")  # noqa

    output_dir_sft = Path(args.model_dir) / "output_sft"
    model, tokenizer = finetune(
        model_name=base_model_name,
        output_dir=str(output_dir_sft),
        dataset_huggingface_workspace=args.dataset_huggingface_workspace,
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        learning_rate=args.learning_rate,
    )
    inference(model, tokenizer)

    sft_output_model_repo_id = (
        f"{args.model_output_huggingface_workspace}/LLMTwinLlama-3.1-8B"
    )
    save_model(
        model,
        tokenizer,
        "model_sft",
        push_to_hub=True,
        repo_id=sft_output_model_repo_id,
    )
