import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { Run } from "@/types/run";

interface RunTrendChartProps {
  runs: Run[];
}

interface ChartDataPoint {
  date: string;
  defects: number;
  runs: number;
}

function buildChartData(runs: Run[]): ChartDataPoint[] {
  // Group runs by day (last 30 days)
  const byDay = new Map<string, { defects: number; runs: number }>();
  const sorted = [...runs].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  );

  for (const run of sorted) {
    const day = new Date(run.start_time).toLocaleDateString("en-GB", {
      month: "short",
      day: "numeric",
    });
    const existing = byDay.get(day) ?? { defects: 0, runs: 0 };
    byDay.set(day, {
      defects: existing.defects + (run.defect_count ?? 0),
      runs: existing.runs + 1,
    });
  }

  return Array.from(byDay.entries()).map(([date, data]) => ({
    date,
    ...data,
  }));
}

const TOOLTIP_STYLE = {
  backgroundColor: "#1C1F26",
  border: "1px solid #2C313C",
  borderRadius: "6px",
  fontFamily: '"IBM Plex Mono", monospace',
  fontSize: "12px",
  color: "#E8E6E1",
};

export function RunTrendChart({ runs }: RunTrendChartProps) {
  const data = buildChartData(runs);

  if (data.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Defects per Day</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#2C313C"
                vertical={false}
              />
              <XAxis
                dataKey="date"
                tick={{ fill: "#9B9690", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                axisLine={{ stroke: "#2C313C" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#9B9690", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                cursor={{ fill: "#2C313C" }}
                formatter={(value) => [
                typeof value === 'number' ? value : 0,
                "defects",
              ]}
              />
              <Bar dataKey="defects" fill="#E8A33D" radius={[3, 3, 0, 0]} maxBarSize={32} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
