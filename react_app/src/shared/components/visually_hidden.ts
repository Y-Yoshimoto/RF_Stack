// 画面には出さず、スクリーンリーダーにだけ読み上げさせる sx (MUI の visuallyHidden と同じ定義)
// 注意: MUI の sx では 1 以下の数値は割合として扱われる (width: 1 は 100%)。そのため 1px は文字列で指定する。
// 数値で書くと position: absolute の領域が親の幅いっぱいになり、ページが横にはみ出す (モバイルでは表示領域が広がる)。
export const VISUALLY_HIDDEN = {
    border: 0,
    clip: 'rect(0 0 0 0)',
    clipPath: 'inset(50%)',
    height: '1px',
    margin: '-1px',
    overflow: 'hidden',
    padding: 0,
    position: 'absolute',
    whiteSpace: 'nowrap',
    width: '1px',
} as const;
