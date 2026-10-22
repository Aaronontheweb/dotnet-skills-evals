# Reuse the same SDK, research helper and instrumented ILSpy installation.
# Build the Seq fixture first with `dotnet-evals prepare-ilspy`.
FROM dotnet-evals-ilspy:seq-7.0.0

USER root
RUN rm -rf /workspace/repo
COPY app/ /workspace/repo/
WORKDIR /workspace/repo
RUN git init \
    && git add Program.cs SupportConsole.csproj packages.lock.json README.md \
    && GIT_AUTHOR_DATE=2026-10-22T00:00:00Z GIT_COMMITTER_DATE=2026-10-22T00:00:00Z \
       git -c user.name='Eval Fixture' -c user.email=fixture@example.invalid \
       commit -m 'Pin support console fixture' \
    && dotnet restore --locked-mode --source https://api.nuget.org/v3/index.json -p:NuGetAudit=false \
    && dotnet build --no-restore -c Release

COPY manifest.py /opt/fixture/manifest.py
RUN python3 /opt/fixture/manifest.py > /opt/fixture/manifest.json \
    && chmod 600 /opt/fixture/manifest.json /opt/fixture/manifest.py

USER eval
CMD ["sleep", "infinity"]
