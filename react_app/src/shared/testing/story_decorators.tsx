// Storybook のストーリー用の共通デコレーター (アプリ本体からは import しない)
import type { Decorator } from '@storybook/react-vite';
import { MemoryRouter } from 'react-router-dom';

/**
 * 画面を MemoryRouter で包むデコレーター (Link / NavLink / Outlet を使う画面用)
 * 最初に表示するパスは parameters.initial_path で指定する (既定は `/`)。
*/
// eslint-disable-next-line @typescript-eslint/naming-convention -- Storybook のデコレーターは第 1 引数をコンポーネント (<Story />) として描画する慣習のため
export const withMemoryRouter: Decorator = (Story, context) => (
    <MemoryRouter initialEntries={[String(context.parameters.initial_path ?? '/')]}>
        <Story />
    </MemoryRouter>
);
