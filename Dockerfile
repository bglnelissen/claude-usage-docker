FROM python:3.13-slim

# Claude Code is pinned: /usage is plain text and an update can change the
# wording (2.1.267 and 2.1.268 already differ). To update: raise this, rebuild,
# run the tests.
ARG CLAUDE_VERSION=2.1.268

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 claude \
 && mkdir /data && chown claude:claude /data

USER claude
RUN curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_VERSION}

# The login and all Claude Code settings live in /data, a volume.
ENV PATH=/home/claude/.local/bin:$PATH \
    CLAUDE_CONFIG_DIR=/data \
    DISABLE_AUTOUPDATER=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --chown=claude:claude claude_usage.py server.py test_claude_usage.py ./

EXPOSE 8130
HEALTHCHECK --interval=60s --timeout=5s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8130/health', timeout=4)"
CMD ["python3", "server.py"]
