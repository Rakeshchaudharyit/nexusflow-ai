import { DatasetDetail } from "@/components/evaluation/dataset-detail";

export const metadata = { title: "Evaluation dataset · NexusFlow AI" };

export default async function DatasetPage({ params }: { params: Promise<{ datasetId: string }> }) {
  const { datasetId } = await params;
  return <DatasetDetail key={datasetId} datasetId={datasetId} />;
}
