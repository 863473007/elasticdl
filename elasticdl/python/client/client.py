import argparse
import os

from elasticdl.python.client.image_builder import build_and_push_docker_image
from elasticdl.python.common import k8s_client as k8s

MODEL_ROOT_PATH = "/model_zoo"


def main():
    parser = argparse.ArgumentParser(
        usage="""client.py <command> [<args>]

There are all the supported commands:
train         Submit a ElasticDL distributed training job.
evaluate      Submit a ElasticDL distributed evaluation job.
"""
    )
    subparsers = parser.add_subparsers()
    train_parser = subparsers.add_parser("train", help="client.py train -h")
    train_parser.set_defaults(func=_train)
    _add_train_params(train_parser)

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="client.py evaluate -h"
    )
    evaluate_parser.set_defaults(func=_evaluate)
    _add_evaluate_params(evaluate_parser)

    args, argv = parser.parse_known_args()
    args.func(args, argv)


def _add_train_params(parser):
    parser.add_argument(
        "--model_def",
        help="The directory that contains user-defined model files "
        "or a specific model file",
        required=True,
    )
    parser.add_argument(
        "--docker_image_prefix",
        default="",
        help="The prefix for generated Docker images, if set, the image is "
        "also pushed to the registry",
    )
    parser.add_argument("--image_base", help="Base Docker image.")
    parser.add_argument("--job_name", help="ElasticDL job name", required=True)
    parser.add_argument(
        "--master_resource_request",
        default="cpu=0.1,memory=1024Mi",
        type=str,
        help="The minimal resource required by master, "
        "e.g. cpu=0.1,memory=1024Mi,disk=1024Mi,gpu=1",
    )
    parser.add_argument(
        "--master_resource_limit",
        type=str,
        help="The maximal resource required by master, "
        "e.g. cpu=0.1,memory=1024Mi,disk=1024Mi,gpu=1, "
        "default to master_resource_request",
    )
    parser.add_argument(
        "--worker_resource_request",
        default="cpu=1,memory=4096Mi",
        type=str,
        help="The minimal resource required by worker, "
        "e.g. cpu=1,memory=1024Mi,disk=1024Mi,gpu=1",
    )
    parser.add_argument(
        "--worker_resource_limit",
        type=str,
        help="The maximal resource required by worker, "
        "e.g. cpu=1,memory=1024Mi,disk=1024Mi,gpu=1,"
        "default to worker_resource_request",
    )
    parser.add_argument(
        "--master_pod_priority", help="The requested priority of master pod"
    )
    parser.add_argument(
        "--volume_name", help="The volume name of network file system"
    )
    parser.add_argument(
        "--mount_path", help="The mount path in the Docker container"
    )
    parser.add_argument(
        "--image_pull_policy",
        default="Always",
        help="The image pull policy of master and worker",
    )
    parser.add_argument(
        "--restart_policy",
        default="Never",
        help="The pod restart policy when pod crashed",
    )
    parser.add_argument(
        "--extra_pypi_index", help="The extra python package repository"
    )
    parser.add_argument(
        "--namespace",
        default="default",
        type=str,
        help="The name of the Kubernetes namespace where ElasticDL "
        "pods will be created",
    )
    parser.add_argument(
        "--tensorboard_log_dir",
        default="",
        type=str,
        help="Directory where TensorBoard will look to find "
        "TensorFlow event files that it can display. "
        "TensorBoard will recursively walk the directory "
        "structure rooted at log dir, looking for .*tfevents.* "
        "files. You may also pass a comma separated list of log "
        "directories, and TensorBoard will watch each "
        "directory.",
    )


def _add_evaluate_params(parser):
    # TODO add parameters for evaluation parser..
    pass


def _train(args, argv):
    image_name = build_and_push_docker_image(
        model_zoo=args.model_def,
        base_image=args.image_base,
        docker_image_prefix=args.docker_image_prefix,
        extra_pypi=args.extra_pypi_index,
    )
    _submit(image_name, args, argv)


def _evaluate(args, argv):
    # TODO implement distributed evaluation.
    raise NotImplementedError()


def _model_def_in_docker(model_def):
    return os.path.join(MODEL_ROOT_PATH, os.path.basename(model_def))


def _submit(image_name, args, argv):
    container_args = [
        "-m",
        "elasticdl.python.master.main",
        "--job_name",
        args.job_name,
        "--worker_image",
        image_name,
        "--model_def",
        _model_def_in_docker(args.model_def),
        "--worker_resource_request",
        args.worker_resource_request,
        "--worker_resource_limit",
        args.worker_resource_limit,
        "--namespace",
        args.namespace,
        "--tensorboard_log_dir",
        args.tensorboard_log_dir,
    ]
    container_args.extend(["--image_pull_policy", args.image_pull_policy])
    container_args.extend(["--restart_policy", args.restart_policy])

    if all([args.volume_name, args.mount_path]):
        container_args.extend(
            [
                "--mount_path",
                args.mount_path,
                "--volume_name",
                args.volume_name,
            ]
        )
    elif any([args.volume_name, args.mount_path]):
        raise ValueError(
            "Not both of the parameters volume_name and "
            "mount_path are provided."
        )

    container_args.extend(argv)

    k8s.Client(
        image_name=image_name,
        namespace=args.namespace,
        job_name=args.job_name,
        event_callback=None,
    ).create_master(
        job_name=args.job_name,
        image_name=image_name,
        resource_requests=args.master_resource_request,
        resource_limits=args.master_resource_limit,
        pod_priority=args.master_pod_priority,
        image_pull_policy=args.image_pull_policy,
        volume_name=args.volume_name,
        mount_path=args.mount_path,
        restart_policy=args.restart_policy,
        args=container_args,
    )


if __name__ == "__main__":
    main()