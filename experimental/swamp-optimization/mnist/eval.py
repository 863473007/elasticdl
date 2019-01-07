from __future__ import print_function
import os
import sys
import argparse
import torch
from torchvision import datasets, transforms
import time
import os
import shutil
from models.network import MNISTNet, CIFAR10Net
from models.resnet import ResidualBlock, ResNet, resnet18
import torch.nn as nn
import torch.nn.functional as F
import multiprocessing
from multiprocessing import Process, Queue
import queue
from common import prepare_data_loader
from common import bool_parser


def _validate(data_loader, model, loss_fn, max_batch, batch_size, device):
    eval_loss = 0
    correct = 0
    total = 0
    with torch.no_grad():
        for batch_idx, (batch_x, batch_y) in enumerate(data_loader):
            if device.type == 'cuda':
                batch_x = batch_x.to(device)
                batch_y = batch_y.to(device)
            if batch_idx < max_batch:
                out = model(batch_x)
                loss = loss_fn(out, batch_y)
                eval_loss += loss.data.item()
                _, predicted = torch.max(out.data, 1)
                correct += (predicted == batch_y).sum().item()
                total += len(batch_y)
            else:
                break
    loss_val = round(eval_loss / total * batch_size, 6)
    accuracy = round(float(correct) / total, 6)
    return loss_val, accuracy


def _evaluate(
        job_root_dir,
        max_validate_batch,
        validate_batch_size,
        concurrency,
        use_gpu,
        data_type,
        model_name):
    # Prepare data source
    validation_ds = prepare_data_loader(False, validate_batch_size,
                                        False, data_type)
    validation_jobs = Queue()
    model_class = globals()[model_name]

    # Evaluate all the jobs under job_root_dir.
    for parent, dirs, _ in os.walk(job_root_dir):
        for job_name in dirs:
            if job_name.startswith('swamp_'):
                job_dir = parent + '/' + job_name

                # Start recomputing
                start_time = time.time()
                for root, _, files in os.walk(job_dir):
                    for f in files:
                        if f.startswith('model_params') and f.endswith('.pkl'):
                            meta = f.split('.')[0].split('_')
                            model_owner = meta[2] + '_' + meta[3]
                            if (meta[2] == 'ps'):
                                msg_info = 'validating job {} ps model version {} ...'.format(
                                    job_name, meta[5])
                            else:
                                msg_info = 'validating job {} trainer {} epoch {} batch {} ...'.format(
                                    job_name, meta[3], meta[5], meta[7])
                            work_params = {
                                'validation_ds': validation_ds,
                                'max_batch': max_validate_batch,
                                'batch_size': validate_batch_size,
                                'job_dir': job_dir,
                                'pkl_dir': root,
                                'param_file': f,
                                'timestamp': meta[-1],
                                'msg': msg_info
                            }
                            validation_jobs.put(work_params)
    # check gpu
    gpu_device_num = 0
    if use_gpu and torch.cuda.is_available():
        gpu_device_num = torch.cuda.device_count()
    if concurrency < gpu_device_num:
        concurrency = gpu_device_num

    # Start validation
    start_time = time.time()
    job_procs = []
    device = 'cpu'
    for i in range(concurrency):
        # Add sentinel job for each evaluation process.
        validation_jobs.put({})
        if gpu_device_num:
            device = 'cuda:%d' % (i % gpu_device_num)
        job = _SingleValidationJob(validation_jobs, model_class, device) 
        job_proc = Process(target=job.validate)
        job_proc.start()
        job_procs.append(job_proc)

    for proc in job_procs:
        proc.join()

    end_time = time.time()
    total_cost = int(end_time - start_time)
    print('validation metrics total cost {} seconds'.format(total_cost))


class _SingleValidationJob(object):
    def __init__(self, job_queue, model_class, device):
        self._model = model_class()
        self._model.train(False)
        self._device = device
        self._job_queue = job_queue
        self._loss_fn = nn.CrossEntropyLoss()

    def validate(self):
        device = torch.device(self._device)                                                                                        
        if device.type == 'cuda':                                                                                                  
            gpu_index = device.index                                                                                               
            os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu_index)                                                                    
            map_device = 'cuda:0'                                                                                                  
            device = torch.device(map_device)                                                                                      
        else:                                                                                                                      
            map_device = self._device

        while True:
            param_dict = self._job_queue.get()
            # Found sentinel job and eval process could exit.
            if not param_dict:
                break
            print(param_dict['msg'])
            #model = torch.load(param_dict['job_dir'] + '/model.pkl')
            self._model.load_state_dict(torch.load(
                '{}/{}'.format(param_dict['pkl_dir'], param_dict['param_file']),
                map_location=map_device))
            self._model.to(device)

            loss, accuracy = _validate(
                param_dict['validation_ds'], self._model, 
                self._loss_fn, param_dict['max_batch'], param_dict['batch_size'],
                device)
            eval_filename = param_dict['pkl_dir'] + '/' + \
                param_dict['param_file'].split('.')[0] + '.eval'

            if os.path.exists(eval_filename):
                os.remove(eval_filename)
            with open(eval_filename, 'w') as eval_f:
                eval_f.write(
                    '{}_{}_{}'.format(
                        loss, accuracy, int(
                            param_dict['timestamp'])))

def _prepare():
    args = _parse_args()
    torch.manual_seed(args.seed)
    os.putenv('OMP_NUM_THREADS', '1')
    return args


def _parse_args():
    # Training settings
    parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
    parser.add_argument('--seed', type=int, default=1, metavar='S',
                        help='random seed (default: 1)')
    parser.add_argument('--job-root-dir', default='jobs',
                        help='The root directory of all job result data')
    parser.add_argument(
        '--job-name',
        default=None,
        help='experiment name used for the result data dir name')
    parser.add_argument('--delete-job-data', type=bool_parser, default=False,
                        help='if delete experiment job result data at last.')
    parser.add_argument(
        '--eval-batch-size',
        type=int,
        default=64,
        help='batch size for evaluate model logged by train.py')
    parser.add_argument('--data-type', default='mnist',
                        help='the name of the dataset (mnist, cifar10)')
    parser.add_argument(
        '--model-name',
        default='MNISTNet',
        help='the name of the model (MNISTNet, CIFAR10Net, resnet18)')
    parser.add_argument('--eval-max-batch', type=int, default=sys.maxsize,
                        help='max batch for evaluate model logged by train.py')
    parser.add_argument('--eval-concurrency', type=int,
                        default=int(multiprocessing.cpu_count()/2),
                        help='process concurrency for CPU evaluation')
    parser.add_argument('--use-gpu', type=bool_parser, default=True,
                        help='use GPU for evaluation if it is available')
    return parser.parse_args()


def main():
    args = _prepare()
    # Workaround for pytorch multiprocssing cuda init issue.
    multiprocessing.set_start_method('spawn')
    _evaluate(
        args.job_root_dir,
        args.eval_max_batch,
        args.eval_batch_size,
        args.eval_concurrency,
        args.use_gpu,
        args.data_type,
        args.model_name)


if __name__ == '__main__':
    main()
