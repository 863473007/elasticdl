# Archtecture Overview

(TODO: Add a diagram)

## Tranier / Coordinator interaction

Trainer can be implemented in any language as long as it has the neural network definition and can do training and inferencing with give parameters and data input.

Data input can be from sharded RecordIO/TFRecord files or read from a network stream.

Coordinator gathers stats from trainers and use a local strategy to decide further tasks, compute new hyper parameters and terminate the training process if appropriate.

Trainers are running in a loop. When idle, a trainer fetches a training or evaluation task from Coordinator. When the task is finished, trainer push the results to coordinator and waiting for next task.

Trainer also maintain an RPC interface via which coordinator can directly stop the current task. Coordinator can also query a trainer's progress or ask a trainer to evaluate the current model via RPC interfaces.

Coordinator RPC:

```
message ModelSpec {
    // If both empty use the trainer's local model.
    string model_path;  // If load model from distributed filesystem.
    string trainer_ip;  // If load model from another trainer.
}

message DataFileSpec {
    string path; // path to training data on distributed filesystem.
    int64 start_record; // start from this record in the path.
    int64 num_record;  // Use this many record for training.
}

// Read training data from files.
message DataFilesSpec {
    repeated DataFileSpec files;
}

// Read training data from a stream. In this design we assume data proxy can access the files locally.
message DataStreamSpec {
    string data_proxy_location;  // Data proxy RPC service location
    DateFilesSpec files;
}

message DataSpec {
    oneof data {
        DataFilesSpec files;
        DataStreamSpec stream;
    }
}

message TrainingTaskSpec {
    ModelSpec model;
    DataSpec data;
    HyperParameter hyper_parameter;
}

message EvaluationTaskSpec {
    ModelSpec model;
    DataSpec data;
}

message TaskSpec {
    int64 task_id;
    oneof {
        TrainingTaskSpec training_task;
        EvaluationTaskSpec evaluation_spec;
    }
}

message TaskResult {
    int64 task_id;
    int64 model_id;
    string model_path;  // Model path on the distributed filesystem.
    double loss;
    double accuracy;
    // some stats about the run，e.g. how many record used, time spent, memory usage, GPU percentage, etc.
    RunStats stat;
}

message TrainerInfo {
    int trainer_id;
    int64 trainer_model_id;
}

rpc GetTask(TrainerInfo) returns (TaskSpec);
rpc PushResult(TaskResult) returns (Empty);
```

Trainer RPC

```
message Model {
    int trainer_id;
    int64 model_id;
    // Opaque model data to be parsed by a trainer.
    repeated byte content;
}

message Progress {
    int epoch;
    int iteration;
}

rpc StopTask(Empty) returns (Empty)
rpc GetModel(Empty) returns (Model)
rpc GetProgress(Empty) returns (Progress)
// TraskSpec must use EvaluationTaskSpec with empty ModelSpec.
// Trainer would pause the training if it is in a training task, do the evaluation, then resume the training.
rpc EvaluateCurrentModel(TaskSpec) return(Empty)
```

Data Proxy RPC 

```
message CreateStreamRequest {
    DataFilesSpec spec;
}
message CreateStreamResponse {
    int64 stream_id;
}
rpc CreateStream(CreateStreamRequest) returns (CreateStreamResponse)

message DataBatchRequest {
    int64 start_record;
    int batch_size;
}
message Record {
    // Opaque data to be parsed by trainer.
    repeated byte data;
}
message DataBatchResponse {
    repeated Record batch;
}
rpc ReadData(DataBatchRequest) returns (stream DataBatchResponse)
```

# Open issue
A coordinator is responsible for a model training. There are one or more trainers, and each trainer has one or more docker containers.  
* How to determine the initial trainer number and the corresponding docker container number.
* How to dynamically change the trainer number or the number of docker containers in a trainer.
* Each trainer will have a RPC service, and train/evaluate the model with one or more containers. If more than one container are used, distributed training is used (allreduce or PS).
