// React
import React from 'react';
// MUI Components
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';

// fetch_dataLoader
import { useLoaderData, useNavigate } from "react-router-dom";

type LoaderResponseType = {
  id: number;
  type: string;
  name: string;
  params: string;
};

const SuccessComponent = ({ response }: { response: LoaderResponseType }) => {
  return (
    <>
      <ul data-testid='response-info'>
        <li>Id: {response.id}</li>
        <li>Type: {response.type}</li>
        <li>Name: {response.name}</li>
        <li>Params: {response.params}</li>
      </ul>
    </>
  );
};

export const FetchLoaderSampleComponent: React.FC = () => {
  // loaderから取得したデータを取得
  const fetch_data = useLoaderData() as LoaderResponseType;
  // console.debug('Loader Data:', fetch_data);
  // 読み込み中の状態表示について
  // https://react-router-docs-ja.techtalk.jp/start/framework/pending-ui#保留中の-ui
  return (<InFetchLoaderSampleComponent fetch_data={fetch_data} />)
};

type InFetchLoaderSampleComponentProps = {
  fetch_data: LoaderResponseType;
};

export const InFetchLoaderSampleComponent: React.FC<InFetchLoaderSampleComponentProps> = ({ fetch_data }) => {

  const navigation = useNavigate();
  const requestingActions = () => navigation(`/FetchComponents-loader/${new Date().getTime()}`)

  return (
    <Container>
      <Typography variant='h4' data-testid='fetch-component-title'>Fetch Loader Component</Typography>
      <Box mt={2}>
        <Button variant='contained' onClick={requestingActions} data-testid='request-button'>
          Request
        </Button>
        <br />
        <SuccessComponent response={fetch_data} />
      </Box>
    </Container>
  );
};

export default FetchLoaderSampleComponent;
