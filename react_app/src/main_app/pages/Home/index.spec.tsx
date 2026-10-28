// AP ホームのテスト (機能への入口から ToDo へ遷移できる)
import { describe, expect, it } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import { Route } from 'react-router-dom';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { AppHomePage } from '.';

describe('AP ホーム', () => {
    it('ToDo への入口を、準備中ではなくリンクとして表示する', () => {
        renderAppScreen(<Route path="/alpha/" element={<AppHomePage />} />, { path: '/alpha/', roles: ['member'] });
        const card = screen.getByTestId('app-home-feature-todo');
        expect(within(card).getByRole('link', { name: 'ToDo' })).toHaveAttribute('href', '/alpha/todos');
        expect(card).not.toHaveTextContent('準備中');
    });
});
