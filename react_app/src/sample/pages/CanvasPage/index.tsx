// React
import React, { useState } from 'react';
import { Stage, Layer, Line, Text } from 'react-konva';
// MUI Components
import Container from '@mui/material/Container';

// export const TestSampleComponent: React.FC = () => {
export function TestSampleComponent() {
  // 表示テキストステート
  const [text, setText] = useState<string | null>(null);
  // デバック出力
  console.debug('App text: ' + text);

  return (
    <Container maxWidth='xl'>
      <h1>Canvas</h1>
      <TimeScaleBase />
      {/* <TimeScale /> */}
    </Container>
  );
};

export default TestSampleComponent;

const TimeScale = () => {
  const [isDragging, setIsDragging] = useState(false); // ドラッグ中かどうか

  const hourWidth = 80; // 1時間あたりのピクセル
  const smallTickWidth = hourWidth / 6; // 小目盛り幅 (10分毎)
  const height = 100;
  return (
    <Stage
      width={600}
      height={100}
      draggable
      style={{ border: '1px solid black', cursor: isDragging ? 'grabbing' : 'grab' }}
    >
      <Layer>

      </Layer>

    </Stage>);
}



const TimeScaleBase = () => {
  const width = 1200;
  const height = 200;
  const [offsetX, setOffsetX] = useState(0); // ドラッグ操作のオフセット（Stageのx座標で管理）
  const [isDragging, setIsDragging] = useState(false); // ドラッグ中かどうか
  // 中心の基準時刻（初期は現在時刻を時刻単位で丸めてセット）
  const now = new Date();
  // now.setMinutes(0, 0, 0);
  const [centerTimeMs] = useState<number>(now.getTime());

  const hourWidth = 80; // 1時間あたりのピクセル
  const smallTickWidth = hourWidth / 6; // 小目盛り幅 (10分毎)

  // 中心 X（ワールド座標での基準位置）
  const centerX = width / 2;

  // 表示領域に合わせて必要な時間目盛りを動的に生成する
  // ワールド座標での表示左端・右端を計算
  const worldLeft = -offsetX; // Stage の x が移動しているため
  const worldRight = width - offsetX;

  // 表示領域をカバーするための開始/終了インデックス（時間単位のインデックス）
  const startIndex = Math.floor((worldLeft - centerX) / hourWidth) - 1;
  const endIndex = Math.ceil((worldRight - centerX) / hourWidth) + 1;

  console.log(`worldLeft: ${worldLeft}, worldRight: ${worldRight}, startIndex: ${startIndex}, endIndex: ${endIndex}`);

  const ticks = [] as { x: number; date: Date }[];
  for (let i = startIndex; i <= endIndex; i++) {
    const x = centerX + i * hourWidth;
    const date = new Date(centerTimeMs + i * 60 * 60 * 1000);
    ticks.push({ x, date });
  }

  return (
    <Stage
      width={width}
      height={height}
      draggable
      x={offsetX}
      y={0}
      // 垂直移動を固定して水平のみ移動
      dragBoundFunc={(pos) => ({ x: pos.x, y: 0 })}
      onDragStart={() => setIsDragging(true)}
      onDragMove={(e) => {
        const x = e.target.x();
        setOffsetX(x);
      }}
      onDragEnd={() => setIsDragging(false)}
      style={{ border: '1px solid black', cursor: isDragging ? 'grabbing' : 'grab' }}
    >
      <Layer>
        {ticks.map((t, idx) => (
          <React.Fragment key={idx}>
            {/* 時刻ラベル（時:00） */}
            <Text text={`${t.date.getHours()}:00`} x={t.x - 18} y={height / 2 - 45} fontSize={14} fill="#000" />
            {/* メイン目盛り */}
            <Line points={[t.x, height / 2 - 20, t.x, height / 2 + 20]} stroke="#000" strokeWidth={2} />
            {/* 小目盛り（10分毎） */}
            {Array.from({ length: 5 }).map((_, j) => (
              <Line
                key={`small-${idx}-${j}`}
                points={[t.x + (j + 1) * smallTickWidth, height / 2 - 10, t.x + (j + 1) * smallTickWidth, height / 2 + 10]}
                stroke="#000"
                strokeWidth={1}
              />
            ))}

            {/* 0:00（深夜）の位置に日付ラベルを表示 */}
            {t.date.getHours() === 0 && (
              <Text
                text={t.date.toLocaleDateString()}
                x={t.x - 30}
                y={height / 2 + 25}
                fontSize={12}
                fill="#333"
              />
            )}
          </React.Fragment>
        ))}
      </Layer>
    </Stage>
  );
};
