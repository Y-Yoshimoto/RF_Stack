import React from 'react';
import { Typography, Box, Button } from '@mui/material';
const LoginPage: React.FC = () => {
    return (
        <Box>
            <Typography variant="h4" align="center" gutterBottom>
                ログインページ
            </Typography>
            <Box component="form" noValidate autoComplete="off">
                <Button
                    variant="contained"
                    color="primary"
                    fullWidth
                    onClick={() => {
                        // OIDCフロー開始のため、意図的にフルページ遷移する
                        window.location.href = '/api/auth/login';
                    }}
                >
                    Keycloakでログイン
                </Button>
            </Box>
        </Box>
    );
};

export default LoginPage;
