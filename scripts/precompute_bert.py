import os
import argparse
import torch
import json
# import h5py
import gzip, csv
import numpy as np

from tqdm import tqdm

from torch.nn.utils.rnn import pad_sequence
from transformers import *



def get_sentence_features(batches, tokenizer, model, device):
    features = tokenizer.batch_encode_plus(batches, padding=True,
        return_attention_mask=True, return_token_type_ids=True)
    attention_mask = torch.tensor(features['attention_mask'], device=device)
    input_ids = torch.tensor(features['input_ids'], device=device)
    token_type_ids=torch.tensor(features['token_type_ids'], device=device)

    # (batch, seq_len, nfeature)
    token_embeddings = model(input_ids=input_ids, 
        attention_mask=attention_mask,
        token_type_ids=token_type_ids)[0]

    # mean of embeddings as sentence embeddings
    embeddings = (attention_mask.unsqueeze(-1) * token_embeddings).sum(1) / attention_mask.sum(1).unsqueeze(-1)

    return embeddings


def hdf5_create_dataset(group, input_file, fp16=False):
    global tokenizer, model, device

    print(f'precompute embeddings for {input_file}')
    gname = group.name[1:]
    pbar = tqdm()
    with open(input_file, 'r') as fin:
        batches = []
        cur = 0
        for i, line in enumerate(fin):
            batches.append(line.strip())
            if (i+1) % batch_size == 0:
                with torch.no_grad():
                    embeddings = get_sentence_features(batches, tokenizer, model, device)

                for j, embed in enumerate(embeddings):
                    embed = embed.cpu().numpy()
                    if fp16:
                        embed = embed.astype('float16')
                    group.create_dataset(f'{gname}_{cur}', embed.shape, 
                        dtype='float32' if not fp16 else 'float16', data=embed)
                    cur += 1

                pbar.update(len(batches))
                batches = []

        if len(batches) > 0:
            with torch.no_grad():
                embeddings = get_sentence_features(batches, tokenizer, model, device)

            for j, embed in enumerate(embeddings):
                embed = embed.cpu().numpy()
                if fp16:
                    embed = embed.astype('float16')
                group.create_dataset(f'{gname}_{cur}', embed.shape, 
                    dtype='float32' if not fp16 else 'float16', data=embed)
                cur += 1

def write_np_memmap(dstore, input_file, dtype):
    global tokenizer, model, device

    print(f'precompute embeddings for {input_file}')
    pbar = tqdm()
    with open(input_file, 'r') as fin:
        batches = []
        cur = 0
        for i, line in enumerate(fin):
            batches.append(line.strip())
            if (i+1) % batch_size == 0:
                with torch.no_grad():
                    embeddings = get_sentence_features(batches, tokenizer, model, device)

                dstore[cur:cur+embeddings.size(0)] = embeddings.cpu().numpy().astype(dtype)
                cur += embeddings.size(0)

                pbar.update(len(batches))
                batches = []

        if len(batches) > 0:
            with torch.no_grad():
                embeddings = get_sentence_features(batches, tokenizer, model, device)

            dstore[cur:cur+embeddings.size(0)] = embeddings.cpu().numpy().astype(dtype)
            cur += embeddings.size(0)

def jsonl_create_dataset(output_file, input_file, fp16=False):
    global tokenizer, model, device

    print(f'precompute embeddings for {input_file}')
    pbar = tqdm()
    fout = open(output_file, 'w')

    with open(input_file, 'r') as fin:
        batches = []
        cur = 0
        for i, line in enumerate(fin):
            batches.append(line.strip())
            if (i+1) % batch_size == 0:
                with torch.no_grad():
                    embeddings = get_sentence_features(batches, tokenizer, model, device)

                for j, embed in enumerate(embeddings):
                    embed = embed.cpu().numpy()
                    if fp16:
                        embed = embed.astype('float16')
                    fout.write(json.dumps({cur: embed.tolist()}))
                    fout.write('\n')
                    cur += 1

                pbar.update(len(batches))
                batches = []

        if len(batches) > 0:
            with torch.no_grad():
                embeddings = get_sentence_features(batches, tokenizer, model, device)

            for j, embed in enumerate(embeddings):
                embed = embed.cpu().numpy()
                if fp16:
                    embed = embed.astype('float16')
                fout.write(json.dumps({cur: embed.tolist()}))
                fout.write('\n')
                cur += 1
    fout.close()

def csv_create_dataset(output_file, input_file, fp16=False):
    global tokenizer, model, device

    print(f'precompute embeddings for {input_file}')
    pbar = tqdm()
    fout = gzip.open(output_file, 'wt')
    # fout = open(output_file, 'w')

    fieldnames = ['embedding']
    writer = csv.DictWriter(fout, fieldnames=fieldnames)

    writer.writeheader()
    with open(input_file, 'r') as fin:
        batches = []
        cur = 0
        for i, line in enumerate(fin):
            batches.append(line.strip())
            if (i+1) % batch_size == 0:
                with torch.no_grad():
                    embeddings = get_sentence_features(batches, tokenizer, model, device)

                for j, embed in enumerate(embeddings):
                    embed = embed.cpu().numpy()
                    if fp16:
                        embed = embed.astype('float16')
                    writer.writerow({'embedding': embed.tolist()})
                    cur += 1

                pbar.update(len(batches))
                batches = []

        if len(batches) > 0:
            with torch.no_grad():
                embeddings = get_sentence_features(batches, tokenizer, model, device)

            for j, embed in enumerate(embeddings):
                embed = embed.cpu().numpy()
                if fp16:
                    embed = embed.astype('float16')
                writer.writerow({'embedding': embed.tolist()})
                cur += 1
    fout.close()


MODELS = [BertModel, BertTokenizer, 'bert-base-uncased']

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='pre-compute the Bert embeddings')
    parser.add_argument('dataset', type=str, help='the path to the dataset name')
    parser.add_argument('--numpy', action='store_true', help='store into numpy memmap format')
    parser.add_argument('--template-only', action='store_true', default=False,
        help='only precomputing the template embeddings')
    parser.add_argument('--fp16', action='store_true', default=False, 
        help='whether to use half float point')

    args = parser.parse_args()
    args.cuda = torch.cuda.is_available()

    save_dir = f"precompute_embedding_datasets/{args.dataset}"

    os.makedirs(save_dir, exist_ok=True)

    device = "cuda" if args.cuda else "cpu"

    model_class, tokenizer_class, pretrained_weights = MODELS
    model = model_class.from_pretrained(pretrained_weights)
    tokenizer = tokenizer_class.from_pretrained(pretrained_weights)

    model.to(device)
    model.eval()

    gname_list = ['template'] if args.template_only else ['valid', 'test', 'template', 'train']
    batch_size = 128

    for gname in gname_list:
        if os.path.isfile(f'datasets/{args.dataset}/{gname}.txt'):
            csv_create_dataset(os.path.join(save_dir, f'{args.dataset}.bert.{gname}.csv.gz'), 
                os.path.join(f'datasets/{args.dataset}/{gname}.txt'), args.fp16)
        elif gname != 'test':
            raise ValueError(f'{gname} file must exist')

    # with h5py.File(os.path.join(save_dir, f'{args.dataset}.bert.hdf5'), 'w') as fout:
    #     for gname in ['valid', 'test', 'template', 'train']:
    #         if os.path.isfile(f'datasets/{args.dataset}/{gname}.txt'):
    #             group = fout.create_group(gname)
    #             hdf5_create_dataset(group, os.path.join(f'datasets/{args.dataset}/{gname}.txt'))
    #         elif gname != 'test':
    #             raise ValueError(f'{gname} file must exist')
