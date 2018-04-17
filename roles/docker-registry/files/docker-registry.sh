#!/bin/bash

# Run docker registry
# Author: Dmitri Rubinstein <dmitri.rubinstein@googlemail.com>

docker_registry_port=${DOCKER_REGISTRY_PORT:-5000}
docker_registry_debug_port=${DOCKER_REGISTRY_DEBUG_PORT:-5001}
docker_registry_name=${DOCKER_REGISTRY_NAME:-registry}
docker_registry_image=${DOCKER_REGISTRY_IMAGE:-registry:2}
docker_registry_config=${DOCKER_REGISTRY_CONFIG}

###############################################################

if [ -n "$docker_registry_config" ]; then
    config_volume="-v ${docker_registry_config}:/etc/docker/registry/config.yml:Z"
else
    config_volume=
fi

if [ -n "$docker_registry_debug_port" ]; then
    config_debug_port="-p $docker_registry_debug_port:$docker_registry_debug_port"
else
    config_debug_port=
fi

# exec docker run -d \
#      -p $docker_registry_port:$docker_registry_port \
#      --restart=always \
#      --name "$docker_registry_name" registry:2;;

case "$1" in
    start)
        mkdir -p /var/lib/registry
        # 'Z' suffix on volume setup SELinux context
        # see "man docker-run" for details
        exec /usr/bin/docker run \
             -p $docker_registry_port:$docker_registry_port \
             $config_debug_port \
             --name "$docker_registry_name" \
             -v /var/lib/registry:/var/lib/registry:Z \
             $config_volume \
             "$docker_registry_image"
        ;;
    stop)
        /usr/bin/docker stop -t 2 "$docker_registry_name";
        /usr/bin/docker rm -f "$docker_registry_name"
        ;;
    *)
        echo >&2 "only 'start' or 'stop' are accepted as argument";
        exit 1
        ;;
esac
