# -*- coding:utf-8 -*-
from __future__ import absolute_import, division, print_function
import os
import sys

sys.path.append(os.path.abspath('.'))
os.chdir(sys.path[0])

import argparse
import logging
import os
import torch
import functools

from io import open
from multiprocessing import Pool
from torch.utils.data import (DataLoader, RandomSampler, SequentialSampler)
from tqdm import tqdm
from transformers import BertTokenizer, AdamW, BertConfig
from itertools import cycle

from srd.cores.model import BertForQuestionAnswering
from srd.libs.prepare_data import read_examples, convert_examples_to_features, TextDataset, collate_fn, set_seed, \
    Result, eval_collate_fn, pre_process, FGM
from srd.libs.ema import ExponentialMovingAverage

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                    datefmt='%m/%d/%Y %H:%M:%S',
                    level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()

    # Required parameters
    parser.add_argument("--data_dir", default=None, type=str,
                        help="The input data dir. Should contain the .tsv files (or other data files) for the task.")
    parser.add_argument("--passage_dir", default=None, type=str,
                        help="The passage data dir. Should contain the .tsv files (or other data files) for the task.")
    parser.add_argument("--train_dir", default=None, type=str,
                        help="The train data dir. Should contain the .tsv files (or other data files) for the task.")
    parser.add_argument("--test_dir", default=None, type=str,
                        help="The test data dir. Should contain the .tsv files (or other data files) for the task.")
    parser.add_argument("--train_json_path", default=None, type=str,
                        help="The train json path. Should contain the .tsv files (or other data files) for the task.")
    parser.add_argument("--dev_json_path", default=None, type=str,
                        help="The dev json path. Should contain the .tsv files (or other data files) for the task.")
    parser.add_argument("--model_name_or_path", default=None, type=str,
                        help="")
    parser.add_argument("--output_dir", default=None, type=str,
                        help="The output directory where the model predictions and checkpoints will be written.")
    parser.add_argument("--es_index", default=None, type=str,
                        help="")
    parser.add_argument("--es_ip", default=None, type=str,
                        help="")
    parser.add_argument("--use_ema", action='store_true',
                        help="ema")

    # Other parameters
    parser.add_argument("--max_seq_length", default=256, type=int,
                        help="The maximum total input sequence length after tokenization. Sequences longer than this"
                             " will be truncated, sequences shorter will be padded.")
    parser.add_argument("--max_question_length", default=50, type=int,
                        help="The maximum total input sequence length after tokenization. Sequences longer than this"
                             " will be truncated, sequences shorter will be padded.")
    parser.add_argument("--do_train", action='store_true',
                        help="Whether to run training.")
    parser.add_argument("--do_test", action='store_true',
                        help="Whether to run training.")
    parser.add_argument("--do_eval", action='store_true',
                        help="Whether to run eval on the dev set.")
    parser.add_argument("--do_eval_train", action='store_true',
                        help="Whether to run eval on the train set.")
    parser.add_argument("--per_gpu_train_batch_size", default=8, type=int,
                        help="Batch size per GPU/CPU for training.")
    parser.add_argument("--per_gpu_eval_batch_size", default=8, type=int,
                        help="Batch size per GPU/CPU for evaluation.")
    parser.add_argument('--gradient_accumulation_steps', type=int, default=1,
                        help="Number of updates steps to accumulate before performing a backward/update pass.")
    parser.add_argument("--learning_rate", default=1e-5, type=float,
                        help="The initial learning rate for Adam.")
    parser.add_argument("--k", default=1, type=int, help="")
    parser.add_argument("--weight_decay", default=0.0, type=float,
                        help="Weight deay if we apply some.")
    parser.add_argument("--adam_epsilon", default=1e-8, type=float,
                        help="Epsilon for Adam optimizer.")
    parser.add_argument("--eval_steps", default=-1, type=int,
                        help="")
    parser.add_argument("--train_steps", default=-1, type=int,
                        help="")
    parser.add_argument("--warmup_steps", default=0, type=int,
                        help="Linear warmup over warmup_steps.")
    parser.add_argument('--seed', type=int, default=1,
                        help="random seed for initialization")

    args = parser.parse_args()

    # ########## local train ##########
    project_dir = '/home/wjunneng/Ubuntu/2020-DataFountain-Outbreak-Assistant'
    args.model_name_or_path = os.path.join(project_dir, 'data', 'prev_trained_model', 'chinese_roberta_wwm_ext_pytorch')
    args.do_train = True
    args.do_eval = True
    args.es_index = 'passages'
    args.es_ip = 'localhost'
    args.data_dir = os.path.join(project_dir, 'data')
    args.train_dir = os.path.join(project_dir, 'data', 'fold', 'train.csv')
    args.test_dir = os.path.join(project_dir, 'data', 'fold', 'test.csv')
    args.passage_dir = os.path.join(project_dir, 'data', 'fold', 'passage.csv')
    args.train_json_path = os.path.join(project_dir, 'data', 'fold', 'train.json')
    args.dev_json_path = os.path.join(project_dir, 'data', 'fold', 'dev.json')
    args.output_dir = os.path.join(project_dir, 'output')
    args.max_seq_length = 512
    args.max_question_length = 96
    args.eval_steps = 100
    args.per_gpu_train_batch_size = 2
    args.per_gpu_eval_batch_size = 2
    args.learning_rate = 1e-5
    args.train_steps = 1500
    args.use_ema = True

    # ########## local test ##########
    # args.model_name_or_path = '/home/wjunneng/Ubuntu/NLP/2020_4/COVID19_qa_baseline/chinese_roberta_wwm_ext_pytorch'
    # args.do_test = True
    # args.k = 5
    # args.es_index = 'passages'
    # args.es_ip = 'localhost'
    # args.data_dir = './data'
    # args.test_dir = './data/test.csv'
    # args.passage_dir = './data/passage.csv'
    # args.output_dir = './output/'
    # args.max_seq_length = 512
    # args.max_question_length = 96
    # args.eval_steps = 100
    # args.per_gpu_train_batch_size = 16
    # args.per_gpu_eval_batch_size = 16
    # args.learning_rate = 1e-5
    # args.train_steps = 1500

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.n_gpu = torch.cuda.device_count()

    # Set seed
    set_seed(args)

    try:
        os.makedirs(args.output_dir)
    except:
        pass

    tokenizer = BertTokenizer.from_pretrained(args.model_name_or_path)
    config = BertConfig.from_pretrained(args.model_name_or_path, num_labels=2)

    args.eval_batch_size = args.per_gpu_eval_batch_size * max(1, args.n_gpu)

    if args.do_train:
        # Prepare model
        model = BertForQuestionAnswering.from_pretrained(args.model_name_or_path, config=config)
        model.to(device)
        fgm = FGM(model)

        if args.n_gpu > 1:
            model = torch.nn.DataParallel(model)

        args.train_batch_size = args.per_gpu_train_batch_size * max(1, args.n_gpu)

        train_examples = read_examples(args.train_dir, args.passage_dir, is_training=1)
        convert_func = functools.partial(convert_examples_to_features,
                                         tokenizer=tokenizer,
                                         max_seq_length=args.max_seq_length,
                                         max_question_length=args.max_question_length,
                                         is_training=1)
        # 线程池处理数据
        with Pool(10) as p:
            train_features = p.map(convert_func, train_examples)
        train_features = pre_process(train_features)
        train_data = TextDataset(train_features)
        train_sampler = RandomSampler(train_data)
        train_dataloader = DataLoader(train_data, sampler=train_sampler,
                                      batch_size=args.train_batch_size // args.gradient_accumulation_steps,
                                      collate_fn=collate_fn)

        num_train_optimization_steps = args.train_steps

        # Prepare optimizer

        param_optimizer = list(model.named_parameters())

        # optimizer
        param_optimizer = [n for n in param_optimizer]

        no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
        optimizer_grouped_parameters = [
            {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)],
             'weight_decay': args.weight_decay},
            {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
        ]

        optimizer = AdamW(optimizer_grouped_parameters, lr=args.learning_rate, eps=args.adam_epsilon)
        if args.use_ema:
            ema = ExponentialMovingAverage(model.parameters(), decay=0.80)

        global_step = 0

        logger.info("***** Running training *****")
        logger.info("  Train file: %s", os.path.join(args.data_dir, 'train1.csv'))
        logger.info("  Num examples = %d", len(train_examples))
        logger.info("  Num selected features = %d", len(train_features))
        logger.info("  Batch size = %d", args.train_batch_size)
        logger.info("  Num steps = %d", num_train_optimization_steps)
        logger.info("  Learning rate = %f", args.learning_rate)

        best_acc = 0
        model.train()
        tr_loss = 0
        nb_tr_examples, nb_tr_steps = 0, 0
        bar = tqdm(range(num_train_optimization_steps), total=num_train_optimization_steps)
        train_dataloader = cycle(train_dataloader)

        output_eval_file = os.path.join(args.output_dir, "eval_results.txt")
        with open(output_eval_file, "w") as writer:
            writer.write('*' * 80 + '\n')
            writer.write(args.data_dir + '\n')
        for step in bar:
            batch = next(train_dataloader)
            input_ids, input_mask, segment_ids, labels = batch
            y_label = [y.to(device) for y in labels]
            loss = model(input_ids=input_ids.to(device), token_type_ids=segment_ids.to(device),
                         attention_mask=input_mask.to(device), labels=y_label)
            if args.n_gpu > 1:
                # mean() to average on multi-gpu.
                loss = loss.mean()
            if args.gradient_accumulation_steps > 1:
                loss = loss / args.gradient_accumulation_steps
            tr_loss += loss.item()
            train_loss = round(tr_loss * args.gradient_accumulation_steps / (nb_tr_steps + 1), 4)
            bar.set_description("loss {}".format(train_loss))
            nb_tr_examples += input_ids.size(0)
            nb_tr_steps += 1

            loss.backward()
            # 对抗训练
            # 在embedding上添加对抗扰动
            fgm.attack()
            loss_adv = model(input_ids=input_ids.to(device), token_type_ids=segment_ids.to(device),
                             attention_mask=input_mask.to(device), labels=y_label)
            if args.n_gpu > 1:
                # mean() to average on multi-gpu.
                loss_adv = loss_adv.mean()
            if args.gradient_accumulation_steps > 1:
                loss_adv = loss_adv / args.gradient_accumulation_steps
            # 反向传播，并在正常的grad基础上，累加对抗训练的梯度
            loss_adv.backward()
            # 恢复embedding参数
            fgm.restore()

            if (nb_tr_steps + 1) % args.gradient_accumulation_steps == 0:
                optimizer.step()
                optimizer.zero_grad()
                global_step += 1

                if args.use_ema:
                    ema.update(model.parameters())

            if (step + 1) % (args.eval_steps * args.gradient_accumulation_steps) == 0:
                tr_loss = 0
                nb_tr_examples, nb_tr_steps = 0, 0
                logger.info("***** Report result *****")
                logger.info("  %s = %s", 'global_step', str(global_step))
                logger.info("  %s = %s", 'train loss', str(train_loss))

            if args.do_eval and (step + 1) % (args.eval_steps * args.gradient_accumulation_steps) == 0:
                if args.do_eval_train:
                    file_list = [args.train_json_path, args.dev_json_path]
                else:
                    file_list = [args.dev_json_path]
                for file in file_list:
                    eval_examples = read_examples(file, args.passage_dir, is_training=2)
                    convert_func_eval = functools.partial(convert_examples_to_features,
                                                          tokenizer=tokenizer,
                                                          max_seq_length=args.max_seq_length,
                                                          max_question_length=args.max_question_length,
                                                          is_training=2)
                    with Pool(10) as p:
                        eval_features = p.map(convert_func_eval, eval_examples)
                    eval_examples = []
                    for eval_feature in eval_features:
                        for feature in eval_feature:
                            eval_examples.append(feature)
                    eval_data = TextDataset(eval_examples)

                    logger.info("***** Running evaluation *****")
                    logger.info("  Eval file = %s", os.path.join(args.data_dir, file))
                    logger.info("  Num examples = %d", len(eval_features))
                    logger.info("  Num selected features = %d", len(eval_data))
                    logger.info("  Batch size = %d", args.eval_batch_size)

                    # Run prediction for full data
                    eval_sampler = SequentialSampler(eval_data)
                    eval_dataloader = DataLoader(eval_data, sampler=eval_sampler, batch_size=args.eval_batch_size,
                                                 collate_fn=eval_collate_fn)

                    if args.use_ema:
                        ema.copy_to(model.parameters())
                    else:
                        model.eval()
                    with torch.no_grad():
                        result = Result()
                        for input_ids, input_mask, segment_ids, examples in tqdm(eval_dataloader):
                            input_ids = input_ids.to(device)
                            input_mask = input_mask.to(device)
                            segment_ids = segment_ids.to(device)
                            y_preds = model(input_ids=input_ids, token_type_ids=segment_ids, attention_mask=input_mask)
                            start_preds, end_preds, class_preds = (p.detach().cpu() for p in y_preds)
                            result.update(examples, start_preds, end_preds, class_preds, 10)

                    scores, predict_df = result.score()
                    model.train()
                    result = {'eval_accuracy': scores,
                              'global_step': global_step,
                              'loss': train_loss}

                    with open(output_eval_file, "a") as writer:
                        writer.write(file)
                        for key in sorted(result.keys()):
                            logger.info("  %s = %s", key, str(result[key]))
                            writer.write("%s = %s\n" % (key, str(result[key])))
                        writer.write('*' * 80)
                        writer.write('\n')
                    if scores > best_acc and 'dev' in file:
                        print("=" * 80)
                        print("Best ACC", scores)
                        print("Saving Model......")
                        best_acc = scores
                        # save predict dataframe
                        predict_df.to_csv(os.path.join(args.output_dir, 'eval_prediction_text.csv'), header=True,
                                          index=False)
                        # Save a trained model
                        model_to_save = model.module if hasattr(model,
                                                                'module') else model  # Only save the model it-self
                        output_model_file = os.path.join(args.output_dir, "pytorch_model.bin")
                        torch.save(model_to_save.state_dict(), output_model_file)
                        print("=" * 80)
                    else:
                        print("=" * 80)
        with open(output_eval_file, "a") as writer:
            writer.write('bert_acc: %f' % best_acc)

    if args.do_test:
        args.do_train = False
        model = BertForQuestionAnswering.from_pretrained(os.path.join(args.output_dir, "pytorch_model.bin"),
                                                         config=config)
        model.to(device)

        test_file = args.test_dir
        if args.n_gpu > 1:
            model = torch.nn.DataParallel(model)

        test_examples = read_examples(test_file, args.passage_dir, is_training=3, k=args.k, es_index=args.es_index,
                                      es_ip=args.es_ip)
        convert_func_eval = functools.partial(convert_examples_to_features,
                                              tokenizer=tokenizer,
                                              max_seq_length=args.max_seq_length,
                                              max_question_length=args.max_question_length,
                                              is_training=3)
        with Pool(10) as p:
            test_features = p.map(convert_func_eval, test_examples)
        test_examples = []
        for test_feature in test_features:
            for feature in test_feature:
                test_examples.append(feature)
        test_data = TextDataset(test_examples)

        logger.info("***** Running Prediction *****")
        logger.info("  Test file = %s", test_file)
        logger.info("  Num examples = %d", len(test_features))
        logger.info("  Num selected features = %d", len(test_data))
        logger.info("  Batch size = %d", args.eval_batch_size)

        test_sampler = SequentialSampler(test_data)
        test_dataloader = DataLoader(test_data, sampler=test_sampler, batch_size=args.eval_batch_size,
                                     collate_fn=eval_collate_fn)

        model.eval()
        with torch.no_grad():
            result = Result(is_testing=1)
            for input_ids, input_mask, segment_ids, examples in tqdm(test_dataloader):
                input_ids = input_ids.to(device)
                input_mask = input_mask.to(device)
                segment_ids = segment_ids.to(device)
                y_preds = model(input_ids=input_ids, token_type_ids=segment_ids, attention_mask=input_mask)
                start_preds, end_preds, class_preds = (p.detach().cpu() for p in y_preds)
                result.update(examples, start_preds, end_preds, class_preds, 5)

        predictions = result.score()

        predictions.to_csv(os.path.join(args.output_dir, 'test_prediction.csv'), index=False, header=True, sep='\t')
        logger.info('predict done')


if __name__ == "__main__":
    main()
