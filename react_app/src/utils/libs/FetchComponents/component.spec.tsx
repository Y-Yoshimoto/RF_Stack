import React from 'react';
// vitestの動作環境確認サンプルコード
/* eslint-disable */
import { describe, it, expect, vi } from 'vitest';
import '@testing-library/jest-dom';
import { render, waitFor, act, screen } from '@testing-library/react';

// テスト対象の関数
import FetchComponent from './component';

// テスト用の仮コンポーネント
const SampleSuccess = ({ response }: { response: any }): React.ReactElement => {
  return <>{response.message}</>;
};
const SampleComponent = () => {
  return <FetchComponent resource_obj={{ url: 'https://example.com' }} renderSuccess={SampleSuccess} />;
};

// Fetchのモックを生成する関数
const genMockFetch = ({ bodyObj = {}, status = 200, statusText = '' }) => {
  const body = JSON.stringify(bodyObj);
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { status, statusText }));
};

describe('Fetchモック動作確認', () => {
  it('リクエスト成功', async () => {
    const data = { message: '200 OK.' };
    const _ = genMockFetch({ bodyObj: data });

    // Suspenseを使用しているためact内でrenderを実行する
    const page = await act(async () => (render(<SampleComponent />)));

    // 200 OK.が表示されることを確認する
    await waitFor(() => {
      expect(page.getByText('200 OK.')).toBeInTheDocument();
    }), { timeout: 1000 };
  });

  it('リクエスト失敗', async () => {
    const _ = genMockFetch({ status: 503, statusText: 'Test Error. ' });

    // Suspenseを使用しているためact内でrenderを実行する
    const page = await act(async () => (render(<SampleComponent />)));

    // Error. Internal Server Errorが表示されることを確認する
    await waitFor(() => {
      expect(page.getByText('Error.')).toBeInTheDocument();
    }), { timeout: 1000 };

  });
});
