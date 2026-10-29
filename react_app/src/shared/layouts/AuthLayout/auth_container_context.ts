// AuthContainer が入れ子になったときに、外側の Container を二重にしないための印
import { createContext } from 'react';

export const AuthContainerContext = createContext<boolean>(false);
