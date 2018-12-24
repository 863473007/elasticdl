from __future__ import print_function
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
from torchvision import datasets, transforms
import sys
import pickle
from multiprocessing import Process, Queue, Manager
from ctypes import py_object
import queue
import time
import gc
from matplotlib import pyplot as plot
import random


class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1, 20, 5, 1)
        self.conv2 = nn.Conv2d(20, 50, 5, 1)
        self.fc1 = nn.Linear(4 * 4 * 50, 500)
        self.fc2 = nn.Linear(500, 10)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2, 2)
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2, 2)
        x = x.view(-1, 4 * 4 * 50)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return F.log_softmax(x, dim=1)


class TrainedModel(object):
    ''' Model uploaded to PS by trainers
    '''

    def __init__(self, model_state, optm_state, loss=float("inf"), version=1):
        self.model_state = model_state
        self.optm_state = optm_state
        self.loss = loss
        self.version = version


class Trainer(object):

    def __init__(
            self,
            tid,
            args,
            trained_model_wrapper,
            up,
            losses,
            timestamps,
            pulled_losses,
            pull_timestamps):
        """ Initialize the Trainer.

        Arguments:
          tid: The unique identifier of the trainer.
          args: Runtime arguments.
          trained_model_wrapper: The info(eg. state, loss) of the best uploaded
                                 model at present model shared by PS and trainer
                                 which is managed by Manager.
          up: A shared Queue for trainer upload model to PS.
          losses: A shared list used for the main process to trace loss which
                  is managed by Manager.
          timestamps: A shared list used for the main process to trace timestamp
                      which is managed by Manager.
          pulled_losses: A shared list used for the main process to trace pulled
                         model loss from ps which is managed by Manager.
          pull_timestamps: A shared list used for the main process to trace
                             pulling timestamp which is managed by Manager.
        """
        self.tid = tid
        self._args = args
        self._up = up
        self._time_costs = timestamps
        self._losses = losses
        self._pulled_losses = pulled_losses
        self._pull_timestamps = pull_timestamps
        self._start_time = time.time()
        self._model = Net()
        self._optimizer = optim.SGD(self._model.parameters(), lr=self._args.lr,
                                    momentum=self._args.momentum)
        self._score = float("inf")
        self._trained_model_wrapper = trained_model_wrapper

    def train(self):
        data_loader = self._prepare_dataloader(self._args.batch_size)
        step = 0

        # start local training
        for epoch in range(self._args.epochs):
            for batch_idx, (data, target) in enumerate(data_loader):
                self._optimizer.zero_grad()
                output = self._model(data)
                loss = F.nll_loss(output, target)

                if step < self._args.free_trial_steps:
                    loss.backward()
                    self._optimizer.step()
                    step = step + 1
                else:
                    if loss.data < self._score:
                        self._push_model(loss)
                    else:
                        if random.random() < self._args.pull_probability:
                            self._pull_model()
                    step = 0

                gc.collect()
                if batch_idx % self._args.loss_sample_interval == 0:
                    self._record_loss(loss)
                self._print_progress(epoch, batch_idx)
            print("trainer %i done epoch %i" % (self.tid, epoch))

    def _prepare_dataloader(self, batch_size):
        kwargs = {}
        return torch.utils.data.DataLoader(
            datasets.MNIST('./data',  # cache data to the current directory.
                           train=True,  # use the training data also for dev.
                           download=True,
                           transform=transforms.Compose([
                               transforms.ToTensor(),
                               transforms.Normalize((0.1307,), (0.3081,))
                           ])),
            batch_size=batch_size,
            shuffle=True,        # each trainer might have different order
            **kwargs)

    def _pull_model(self):
        trained_model = self._trained_model_wrapper.value
        self._model.load_state_dict(trained_model.model_state)
        self._optimizer.load_state_dict(trained_model.optm_state)
        self._score = trained_model.loss
        self._pulled_losses.append(self._score.data.item())
        self._pull_timestamps.append(self._timestamps())

    def _push_model(self, loss):
        self._score = loss.data
        if self._up is not None:
            upload_model = TrainedModel(
                self._model.state_dict(),
                self._optimizer.state_dict(),
                loss.data)
            self._up.put(pickle.dumps(upload_model))

    def _record_loss(self, loss):
        if self._args.loss_file is not None:
            self._time_costs.append(self._timestamps())
            self._losses.append(round(loss.item(), 4))

    def _print_progress(self, epoch, batch_idx):
        if batch_idx % self._args.log_interval == 0:
            print("Current trainer id: %i, epoch: %i, batch id: %i" %
                  (self.tid, epoch, batch_idx))

    def _timestamps(self):
        return round(time.time() - self._start_time, 4)


class PS(object):

    def __init__(self, args, trained_model_wrapper, up, losses, timestamps):
        """ Initialize the PS.

        Arguments:
          args: Runtime arguments.
          trained_model_wrapper: The info(eg. state, loss) of the best uploaded
                                 model at present shared by PS and trainer which
                                 is managed by Manager.
          up: A shared Queue for trainer upload model to PS.
          losses: A shared list used for the main process to trace loss which
                  is managed by Manager.
          timestamps: A shared list used for the main process to trace timestamp
                      which is managed by Manager.
        """
        self._args = args
        self._up = up
        self._time_costs = timestamps
        self._losses = losses
        self._exit = False
        self._start_time = time.time()
        self._model = Net()
        self._trained_model_wrapper = trained_model_wrapper
        self._score = float("inf")

    def run(self):
        updates = 0
        validate_loader = self._prepare_validation_loader()

        while not self._exit:
            # In the case that any trainer pushes.
            try:
                d = self._up.get(timeout=1.0)
            except queue.Empty:
                continue

            # Restore uploaded model
            upload_model = pickle.loads(d)
            self._model.load_state_dict(upload_model.model_state)

            if upload_model.loss < self._score:
                # Model double check
                double_check_loss = self._validate(validate_loader)
                if double_check_loss < self._score:
                    self._update_model_wrapper(upload_model)
                    self._record_loss(self._score)

    def _prepare_validation_loader(self):
        return torch.utils.data.DataLoader(
            datasets.MNIST('./data',
                           train=False,
                           download=True,
                           transform=transforms.Compose([
                               transforms.ToTensor(),
                               transforms.Normalize((0.1307,), (0.3081,))
                           ])),
            batch_size=self._args.validate_batch_size,
            shuffle=True)  # shuffle for random test

    def _validate(self, data_loader):
        max_batch = self._args.validate_max_batch
        eval_loss = 0
        with torch.no_grad():
            for batch_idx, (batch_x, batch_y) in enumerate(data_loader):
                if batch_idx < max_batch:
                    out = self._model(batch_x)
                    loss = F.nll_loss(out, batch_y)
                    eval_loss += loss.data.item()
                else:
                    break
        loss_val = eval_loss / max_batch
        return loss_val

    def _update_model_wrapper(self, upload_model):
        if self._trained_model_wrapper.value is not None:
            upload_model.version = self._trained_model_wrapper.value.version + 1
            self._trained_model_wrapper.value = upload_model
        else:
            self._trained_model_wrapper.value = upload_model
        self._score = upload_model.loss

    def _record_loss(self, loss):
        if self._args.loss_file is not None:
            self._time_costs.append(round(time.time() - self._start_time))
            self._losses.append(round(loss.item(), 4))


def parse_args():
    # Training settings
    parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
    parser.add_argument('--batch-size', type=int, default=64, metavar='N',
                        help='input batch size for training (default: 64)')
    parser.add_argument('--epochs', type=int, default=1, metavar='N',
                        help='number of epochs to train (default: 1)')
    parser.add_argument('--lr', type=float, default=0.01, metavar='LR',
                        help='learning rate (default: 0.01)')
    parser.add_argument('--momentum', type=float, default=0.5, metavar='M',
                        help='SGD momentum (default: 0.5)')
    parser.add_argument('--seed', type=int, default=1, metavar='S',
                        help='random seed (default: 1)')
    parser.add_argument(
        '--free-trial-steps',
        type=int,
        default=10,
        metavar='N',
        help='how many batches to wait before sync up with the ps')
    parser.add_argument('--save-model', action='store_true', default=False,
                        help='For Saving the current Model')
    parser.add_argument('--validate_batch_size', default=64,
                        help='batch size for validation dataset in ps')
    parser.add_argument('--validate_max_batch', default=5,
                        help='max batch for validate model in ps')
    parser.add_argument('--loss-file', default='curves/loss.png',
                        help='the name of loss figure file')
    parser.add_argument(
        '--loss-sample-interval',
        type=int,
        default=1,
        help='how many batches to wait before record a loss value')
    parser.add_argument(
        '--log-interval',
        type=int,
        default=50,
        metavar='N',
        help='how many batches to wait before logging training status')
    parser.add_argument('--pull-probability', type=float, default=0,
                        help='the probability of trainer pulling from ps')
    parser.add_argument('--trainer-number', type=int, default=1,
                        help='the total number of trainer to launch')
    return parser.parse_args()


def start_ps(args, up, manager, trained_model, loss_dict, timestamp_dict):
    # Init PS process
    key = 'ps'
    # Shared list used by the parent process and trainer for
    # loss tracing
    losses = manager.list()
    timestamps = manager.list()
    loss_dict[key] = losses
    timestamp_dict[key] = timestamps
    ps = PS(args, trained_model, up, losses, timestamps)
    ps_proc = Process(target=ps.run, name='ps')
    ps_proc.start()

    return ps_proc


def start_trainers(
        args,
        up,
        manager,
        trained_model,
        loss_dict,
        timestamp_dict):
    # Init trainer processes
    trainers = []
    trainer_procs = []
    for t in range(args.trainer_number):
        tname = 'trainer-' + str(t)
        tname_with_pull = tname + '-pull'
        # Shared list used by the parent process and ps for loss
        # tracing
        losses = manager.list()
        timestamps = manager.list()
        pulled_losses = manager.list()
        pull_timestamps = manager.list()

        loss_dict[tname] = losses
        timestamp_dict[tname] = timestamps
        loss_dict[tname_with_pull] = pulled_losses
        timestamp_dict[tname_with_pull] = pull_timestamps

        trainer = Trainer(t, args, trained_model, up, losses, timestamps,
                          pulled_losses, pull_timestamps)
        trainer_proc = Process(target=trainer.train, name=tname)
        trainer_proc.start()
        trainers.append(trainer)
        trainer_procs.append(trainer_proc)

    return trainers, trainer_procs


def draw(args, loss_dict, timestamp_dict):
    print("Write image to ", args.loss_file)
    plot.xlabel('timestamp')
    plot.ylabel('loss')
    plot.title(
        'swamp training for mnist data (pull probability %s)' %
        args.pull_probability)
    lowest_loss = find_lowest_loss_in_ps(loss_dict)
    for (k, v) in loss_dict.items():
        if k.endswith('pull'):
            plot.scatter(timestamp_dict[k], v, s=12, label=k)
        elif k == 'ps':
            plot.plot(
                timestamp_dict[k], v, label=(
                    k + ' (lowest-loss: ' + str(lowest_loss) + ')'))
        else:
            plot.plot(timestamp_dict[k], v, label=k)
    plot.legend(loc='upper right', prop={'size': 6})
    plot.savefig(args.loss_file)


def find_lowest_loss_in_ps(loss_dict):
    loss = float("inf")
    losses = loss_dict['ps']
    for v in losses:
        if loss > v:
            loss = v
    return loss


def main():
    args = parse_args()
    torch.manual_seed(args.seed)

    # Data stores shared by PS, trainers and the main process
    up = Queue()
    manager = Manager()
    trained_model = manager.Value(py_object, None)
    loss_dict = {}
    timestamp_dict = {}

    # Start PS and trainers
    ps_proc = start_ps(
        args,
        up,
        manager,
        trained_model,
        loss_dict,
        timestamp_dict)
    trainers, trainer_procs = start_trainers(
        args, up, manager, trained_model, loss_dict, timestamp_dict)

    for proc in trainer_procs:
        proc.join()
    ps_proc.terminate()

    if args.loss_file is not None:
        draw(args, loss_dict, timestamp_dict)


if __name__ == '__main__':
    main()
