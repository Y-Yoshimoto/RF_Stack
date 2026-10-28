import type { Meta, StoryObj } from '@storybook/react-vite';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { NotFoundPage } from '.';

const meta = {
    title: 'Shared/NotFound',
    component: NotFoundPage,
    parameters: { layout: 'fullscreen' },
    decorators: [withMemoryRouter],
} satisfies Meta<typeof NotFoundPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
