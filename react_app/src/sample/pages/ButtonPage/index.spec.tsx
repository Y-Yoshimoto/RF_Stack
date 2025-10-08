// ボタンのテストサンプル
import { expect, describe, it } from 'vitest';
import '@testing-library/jest-dom';
import { render, fireEvent, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event'

// テスト対象
import { TestSampleComponent } from './index';


describe('ボタンテストサンプル', () => {

  // fireEvent
  // actがラップされているので、actを明示する必要はない
  // フックが同期的に実行されるため、actでレンダリングが完了しWaitForで非同期処理を待つ必要がない
  // https://react.dev/link/wrap-tests-with-act
  it('fireEventを使うパターン', () => {
    // コンポーネントをレンダリング
    const { getByText, getByRole, getByTestId, queryByTestId } = render(<TestSampleComponent />);
    // ボタンの文字をテスト
    expect(getByText('primary')).toBeInTheDocument();
    expect(getByText('secondary')).toBeInTheDocument();
    expect(getByText('clear')).toBeInTheDocument();
    // ボタン取得
    const primaryButton = getByRole('button', { name: /primary/i });
    const secondaryButton = getByRole('button', { name: /secondary/i });
    const clearButton = getByRole('button', { name: /clear/i });
    // ボタンをクリック(primary, secondary, clear)
    fireEvent.click(primaryButton);
    expect(getByTestId('text-label')).toHaveTextContent('primary');
    fireEvent.click(secondaryButton);
    expect(getByTestId('text-label')).toHaveTextContent('secondary');
    fireEvent.click(clearButton);
    expect(queryByTestId('text-label')).toBeNull();
  });



  // userEvent
  // fireEventと違って、ユーザーの操作を模倣するため、よりリアルなテストが可能だが、
  // 非同期処理やイベントの順序を考慮する必要がある
  // userEventは、内部でactを使用しているため、actでラップする必要はない
  // ただし、非同期処理を待つためにawait, waitForを使用する必要がある
  // https://testing-library.com/docs/user-event/intro/
  it('useEventを使うパターン', async () => {
    // userEventのセットアップ
    // userEvent.setup()は、ユーザーイベントを模倣するためのセットアップ関数
    const user = userEvent.setup()
    // コンポーネントをレンダリング
    const { getByText, getByRole, getByTestId, queryByTestId } = render(<TestSampleComponent />);
    // ボタンの文字をテスト
    expect(getByText('primary')).toBeInTheDocument();
    expect(getByText('secondary')).toBeInTheDocument();
    expect(getByText('clear')).toBeInTheDocument();
    // ボタン取得
    const primaryButton = getByRole('button', { name: /primary/i });
    const secondaryButton = getByRole('button', { name: /secondary/i });
    const clearButton = getByRole('button', { name: /clear/i });


    // アクション後のプロミスの中で評価する
    await user.click(primaryButton).then(() => {
      expect(getByTestId('text-label')).toHaveTextContent('primary');
    });

    // await waitForでレンダリングを待つ
    await user.click(secondaryButton);
    await waitFor(() => {
      expect(getByTestId('text-label')).toHaveTextContent('secondary');
    }, { timeout: 100 });

    // clearボタンをクリックして、テキストラベルが削除されることを確認
    await user.click(clearButton).then(() => {
      expect(queryByTestId('text-label')).toBeNull();
    });

  });

  it('act内で直接イベントを発火させるパターン', async () => {
    // コンポーネントをレンダリング
    const { getByText, getByRole, getByTestId, queryByTestId } = render(<TestSampleComponent />);
    // ボタンの文字をテスト
    expect(getByText('primary')).toBeInTheDocument();
    expect(getByText('secondary')).toBeInTheDocument();
    expect(getByText('clear')).toBeInTheDocument();
    // ボタン取得
    const primaryButton = getByRole('button', { name: /primary/i });
    const secondaryButton = getByRole('button', { name: /secondary/i });
    const clearButton = getByRole('button', { name: /clear/i });

    // ボタンをクリック(primary, secondary, clear)
    act(() => primaryButton.click());
    expect(getByTestId('text-label')).toHaveTextContent('primary');
    act(() => secondaryButton.click());
    expect(getByTestId('text-label')).toHaveTextContent('secondary');
    act(() => clearButton.click());
    expect(queryByTestId('text-label')).toBeNull();
  });

});
