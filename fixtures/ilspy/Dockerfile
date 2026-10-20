FROM mcr.microsoft.com/dotnet/sdk:10.0.100@sha256:c7445f141c04f1a6b454181bd098dcfa606c61ba0bd213d0a702489e5bd4cd71

ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    DOTNET_ROLL_FORWARD=Major \
    NUGET_PACKAGES=/opt/nuget \
    HOME=/home/eval

RUN apt-get update && apt-get install -y --no-install-recommends python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 eval
RUN dotnet tool install ilspycmd --version 9.1.0.7988 --tool-path /opt/ilspy

# Resolve the tag once, then build from its immutable commit.
RUN git init /workspace/repo \
    && git -C /workspace/repo remote add origin https://github.com/datalust/serilog-sinks-seq.git \
    && git -C /workspace/repo fetch --depth 1 origin bf6c2f8d26803a30b9963e01ea0d5f63152a7006 \
    && git -C /workspace/repo checkout --detach FETCH_HEAD \
    && git config --system --add safe.directory /workspace/repo

# Run outside the checkout so its historical global.json does not select an
# unavailable SDK. The checked-in lock covers both target frameworks.
COPY packages.lock.json /opt/fixture/packages.lock.json
WORKDIR /opt/fixture
RUN dotnet restore /workspace/repo/src/Serilog.Sinks.Seq/Serilog.Sinks.Seq.csproj \
    --locked-mode -p:NuGetLockFilePath=/opt/fixture/packages.lock.json -p:NuGetAudit=false
COPY manifest.py /opt/fixture/manifest.py
RUN python3 /opt/fixture/manifest.py > /opt/fixture/manifest.json \
    && chmod 600 /opt/fixture/manifest.json /opt/fixture/manifest.py

# Both entry points execute the same installed tool and record its real exit
# status and output. These wrappers exist in BOTH experimental conditions.
COPY ilspy_probe.py /opt/fixture/ilspy_probe.py
RUN mv /opt/ilspy/ilspycmd /opt/ilspy/ilspycmd-real \
    && printf '#!/bin/sh\nexec python3 /opt/fixture/ilspy_probe.py "$@"\n' > /opt/ilspy/ilspycmd \
    && ln -s /opt/ilspy/ilspycmd /usr/local/bin/ilspycmd \
    && printf '#!/bin/sh\nif [ "$1" = ilspycmd ]; then shift; exec ilspycmd "$@"; fi\necho "Only the preinstalled ilspycmd package is available offline" >&2\nexit 127\n' > /usr/local/bin/dnx \
    && chmod 755 /opt/ilspy/ilspycmd /usr/local/bin/dnx

USER eval
WORKDIR /workspace/repo
CMD ["sleep", "infinity"]
