"""Thin DataHub GraphQL / OpenAPI client used by the live provider.

GraphQL gives a stable, normalised shape for structural context; the Timeline
API gives real schema change history; mutations are used for the controlled
write-back (tag + institutional memory link).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

DATASET_QUERY = """
query dataForensicDataset($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    origin
    platform { name properties { displayName } }
    properties { name description customProperties { key value } }
    editableProperties { description }
    domain { domain { urn properties { name } } }
    tags { tags { tag { urn name } } }
    glossaryTerms { terms { term { urn name } } }
    ownership { owners { type owner { ... on CorpUser { urn username properties { displayName email } } ... on CorpGroup { urn name } } } }
    schemaMetadata { fields { fieldPath type nativeDataType nullable description } }
    institutionalMemory { elements { url label description created { time } } }
  }
}
"""

ENTITY_QUERY = """
query dataForensicEntity($urn: String!) {
  entity(urn: $urn) {
    urn
    type
    ... on Dataset { name platform { name } properties { name description } ownership { owners { owner { ... on CorpUser { urn username } ... on CorpGroup { urn name } } } } tags { tags { tag { name } } } }
    ... on Dashboard { properties { name description } ownership { owners { owner { ... on CorpUser { urn username } ... on CorpGroup { urn name } } } } tags { tags { tag { name } } } }
    ... on Chart { properties { name description } tags { tags { tag { name } } } }
    ... on MLModel { name properties { description } tags { tags { tag { name } } } }
    ... on MLFeatureTable { name properties { description } }
    ... on DataJob { jobId properties { name description } }
    ... on DataFlow { flowId properties { name description } }
  }
}
"""

LINEAGE_QUERY = """
query dataForensicLineage($urn: String!, $direction: LineageDirection!, $count: Int!) {
  searchAcrossLineage(input: {urn: $urn, direction: $direction, query: "*", start: 0, count: $count}) {
    total
    searchResults {
      degree
      entity {
        urn
        type
        ... on Dataset { name platform { name } properties { name } tags { tags { tag { name } } } ownership { owners { owner { ... on CorpUser { urn username } ... on CorpGroup { urn name } } } } }
        ... on Dashboard { properties { name } ownership { owners { owner { ... on CorpUser { urn username } ... on CorpGroup { urn name } } } } }
        ... on Chart { properties { name } }
        ... on MLModel { name }
        ... on MLFeatureTable { name }
        ... on DataJob { jobId properties { name } }
      }
    }
  }
}
"""

SEARCH_QUERY = """
query dataForensicSearch($query: String!, $count: Int!) {
  searchAcrossEntities(input: {query: $query, start: 0, count: $count}) {
    total
    searchResults { entity { urn type ... on Dataset { name platform { name } } ... on Dashboard { properties { name } } } }
  }
}
"""

ASSERTIONS_QUERY = """
query dataForensicAssertions($urn: String!) {
  dataset(urn: $urn) {
    assertions(start: 0, count: 50) {
      total
      assertions {
        urn
        info { type description }
        runEvents(limit: 1) { runEvents { timestampMillis status result { type nativeResults { key value } } } }
      }
    }
  }
}
"""

CREATE_TAG = """
mutation dataForensicCreateTag($id: String!, $name: String!, $description: String) {
  createTag(input: {id: $id, name: $name, description: $description})
}
"""

ADD_TAGS = """
mutation dataForensicAddTags($tagUrns: [String!]!, $resourceUrn: String!) {
  addTags(input: {tagUrns: $tagUrns, resourceUrn: $resourceUrn})
}
"""

ADD_LINK = """
mutation dataForensicAddLink($linkUrl: String!, $label: String!, $resourceUrn: String!) {
  addLink(input: {linkUrl: $linkUrl, label: $label, resourceUrn: $resourceUrn})
}
"""


class DataHubGraphQLError(RuntimeError):
    pass


class DataHubGraphQLClient:
    def __init__(self, base_url: str, token: str | None, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=headers)
        return self._client

    async def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        client = await self._http()
        response = await client.post(
            f"{self.base_url}/api/graphql",
            json={"query": query, "variables": variables or {}},
        )
        if response.status_code >= 400:
            raise DataHubGraphQLError(
                f"GraphQL HTTP {response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
        if payload.get("errors"):
            raise DataHubGraphQLError(str(payload["errors"])[:400])
        return payload.get("data") or {}

    async def health(self) -> dict[str, Any]:
        client = await self._http()
        response = await client.get(f"{self.base_url}/config")
        response.raise_for_status()
        return response.json()

    async def timeline(
        self, urn: str, start: datetime | None, end: datetime | None, categories: list[str]
    ) -> list[dict[str, Any]]:
        client = await self._http()
        # Parameter names come from the Timeline API guide:
        #   /openapi/v2/timeline/v1/<url-encoded-urn>?categories=TECHNICAL_SCHEMA
        #     &start=<epoch-ms>&end=<epoch-ms>
        # `startTime` / `endTime` are not accepted; a wrong name here does not
        # error, it silently returns the entire history and the temporal
        # correlation stops meaning anything.
        params: dict[str, Any] = {"categories": categories}
        if start:
            params["start"] = int(start.timestamp() * 1000)
        if end:
            params["end"] = int(end.timestamp() * 1000)
        response = await client.get(
            f"{self.base_url}/openapi/v2/timeline/v1/{quote(urn, safe='')}", params=params
        )
        if response.status_code >= 400:
            raise DataHubGraphQLError(
                f"Timeline HTTP {response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
        return payload if isinstance(payload, list) else payload.get("changeTransactions", [])

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
