import { BarChart, H1, H2, LineChart, Stack, Text } from "cursor/canvas";

const bins = ["0–5 px", "5–10 px", "10–20 px", "20–50 px", "50–200 px", "over 200 px"];
const glintBins = [65.0, 17.0, 2.3, 0, 0, 15.7];
const hogBins = [24.7, 34.3, 37.0, 4.0, 0, 0];

const marks = ["1 px", "2 px", "5 px", "8 px", "10 px", "15 px", "20 px", "30 px", "50 px", "100 px", "500 px", "1200 px"];
const glintWithin = [16.0, 30.7, 65.0, 79.0, 82.0, 84.3, 84.3, 84.3, 84.3, 84.3, 86.7, 99.3];
const hogWithin = [5.3, 10.3, 24.7, 46.3, 59.0, 85.3, 96.0, 100, 100, 100, 100, 100];

export default function ErrorDistributions() {
  return (
    <Stack gap={24}>
      <Stack gap={6}>
        <H1>Detection error on the held-out sweeps</H1>
        <Text tone="secondary">
          300 sweep frames. Each sweep was scored with the method fitted on the other sweep plus the steady clips. Glint is strip 972, glint radius 2.5, disk 40. HOG is a 32 px patch, searching 160 px up and down from the last hit. The miss is vertical pixels on the 2592×1944 frame.
        </Text>
      </Stack>
      <Stack gap={8}>
        <H2>Share of frames in each miss range</H2>
        <Text tone="secondary" size="small">
          Percent of the 300 frames. Glint’s frames over 200 px are the wrong bright spot, around 600–1200 px away. None of its misses fall between 20 and 200 px.
        </Text>
        <BarChart
          categories={bins}
          series={[
            { name: "Glint", data: glintBins },
            { name: "HOG", data: hogBins },
          ]}
          valueSuffix="%"
          height={280}
          showValues
        />
      </Stack>
      <Stack gap={8}>
        <H2>Share of frames no worse than a given miss</H2>
        <Text tone="secondary" size="small">
          Read across for a miss size, and up for how many frames are at least that close. HOG reaches every frame by 30 px. Glint is ahead below 15 px, then stays near 84% until the far misses come in.
        </Text>
        <LineChart
          categories={marks}
          series={[
            { name: "Glint", data: glintWithin },
            { name: "HOG", data: hogWithin },
          ]}
          valueSuffix="%"
          height={300}
          fill
        />
      </Stack>
    </Stack>
  );
}
